#!/usr/bin/env python
"""job_bot - search many job platforms, score postings against a resume, render an HTML report.

Typical use:
  python job_bot.py run --role "flutter developer" --experience 3 --countries DE,NL,ES,FI,AU,JP,TH --resume C:\\path\\cv.pdf --open

Sub-commands:
  run                search + (score if --resume) + render          [most people only need this]
  search             search only -> jobs.json / run.json / fallback_plan.json
  score              add resume match scores to an existing run
  render             (re)build report.html from an existing run
  merge              add jobs found elsewhere (JSON list) into a run, re-score, re-render
  apply              apply to a run's LinkedIn postings (Easy Apply) via the Naukri screener's applier
  fallback-queries   print the web-search plan for platforms that block scripts (Indeed, Naukri, ...)
  sources            list available sources and whether they are enabled
  countries          list supported countries
  selftest           quick connectivity check of every source
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from jobbot import __version__  # noqa: E402
from jobbot.config import (COUNTRIES, DEFAULT_COUNTRIES, DEFAULT_DAYS, DEFAULT_DETAILS, DEFAULT_MAX_PER_SOURCE,  # noqa: E402
                           DEFAULT_OUT_ROOT, REMOTE, country_name, resolve_country)
from jobbot.details import fetch_details  # noqa: E402
from jobbot.dotenv import load_env  # noqa: E402
from jobbot.experience import parse_user_experience  # noqa: E402
from jobbot.fallback import fallback_queries, load_extra_file, merge_extra  # noqa: E402
from jobbot.http import Http  # noqa: E402
from jobbot.models import Job  # noqa: E402
from jobbot.render import render  # noqa: E402
from jobbot.resume import ResumeError, extract_text  # noqa: E402
from jobbot.scoring import score_jobs  # noqa: E402
from jobbot.search import apply_fit_filter, run_search, sort_jobs  # noqa: E402
from jobbot.sources import ALL_SOURCES, BY_KEY, select_sources  # noqa: E402
from jobbot.sources.base import SearchContext  # noqa: E402
from jobbot.textutil import slugify  # noqa: E402


# ----------------------------------------------------------------------------- helpers
class Logger:
    def __init__(self, path=None, quiet=False):
        self.path = path
        self.quiet = quiet

    def __call__(self, msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        if not self.quiet:
            print(line, file=sys.stderr, flush=True)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def parse_countries(text):
    if not text:
        return list(DEFAULT_COUNTRIES)
    out, unknown = [], []
    for part in text.replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        code = resolve_country(p)
        if code and code not in out:
            out.append(code)
        elif not code:
            unknown.append(p)
    if unknown:
        print(f"warning: unknown countries ignored: {', '.join(unknown)} (see `countries` command)", file=sys.stderr)
    return out or list(DEFAULT_COUNTRIES)


def make_run_dir(args):
    if args.out:
        path = os.path.abspath(os.path.expanduser(args.out))
    else:
        root = os.path.abspath(os.path.expanduser(args.out_root or DEFAULT_OUT_ROOT))
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        slug = slugify(args.role[0])[:40] or "jobs"
        path = os.path.join(root, f"{stamp}_{slug}")
    os.makedirs(path, exist_ok=True)
    return path


def save_run(run_dir, meta, statuses, jobs):
    with open(os.path.join(run_dir, "jobs.json"), "w", encoding="utf-8") as f:
        json.dump([j.to_dict() for j in jobs], f, ensure_ascii=False, indent=1)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "sources": statuses}, f, ensure_ascii=False, indent=1)


def load_run(run_dir):
    run_dir = os.path.abspath(os.path.expanduser(run_dir))
    with open(os.path.join(run_dir, "run.json"), encoding="utf-8") as f:
        run = json.load(f)
    with open(os.path.join(run_dir, "jobs.json"), encoding="utf-8") as f:
        jobs = [Job.from_dict(d) for d in json.load(f)]
    return run_dir, run.get("meta", {}), run.get("sources", []), jobs


def open_report(path):
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        else:
            import webbrowser
            webbrowser.open("file://" + path)
    except Exception as e:  # noqa: BLE001
        print(f"could not open browser: {e}", file=sys.stderr)


def summary(meta, jobs, statuses, report, log):
    by_cc = {}
    for j in jobs:
        by_cc[j.country] = by_cc.get(j.country, 0) + 1
    log("")
    log(f"RESULT: {len(jobs)} jobs")
    for cc in meta.get("countries", []) + ([REMOTE] if REMOTE in by_cc else []):
        if cc in by_cc:
            log(f"  {country_name(cc):<22} {by_cc.get(cc, 0):>4}")
    bad = [s for s in statuses if s["status"] != "ok"]
    if bad:
        names = sorted({s["source_name"] for s in bad})
        log(f"  unavailable sources: {', '.join(names)} (direct search links are in the report)")
    top = sort_jobs(jobs)[:5]
    if top:
        log("  top:")
        for j in top:
            sc = f"{j.score:>5.1f}" if j.score is not None else "  n/a"
            log(f"    {sc}  {j.fit:<8} {j.country:<6} {j.title[:48]:<48} @ {j.company[:26]}")
    log(f"REPORT: {report}")


# ----------------------------------------------------------------------------- commands
def build_context(args, log, countries):
    user_years = parse_user_experience(args.experience)
    http = Http(log=log, min_interval=args.interval)
    ctx = SearchContext(
        roles=args.role, countries=countries, user_years=user_years, days=args.days,
        hours=getattr(args, "hours", None), allow_undated=getattr(args, "allow_undated", None) or None,
        max_per_source=args.max_per_source, http=http, log=log,
        exclude_terms=[t.strip() for t in (args.exclude or "").split(",") if t.strip()],
        must_terms=[t.strip() for t in (args.must or "").split(",") if t.strip()],
        loose=args.loose, min_relevance=getattr(args, "min_relevance", 0.4),
    )
    return ctx, user_years


def parse_platforms(text):
    """A comma list of platform keys or display names -> source keys.

    Names are matched loosely ("The Muse", "themuse", "muse", "Seek / JobsDB"),
    so the phone's chips and a typed list mean the same thing. Unknown entries
    are returned too, so the caller can say which ones it did not recognise.
    """
    picked, unknown = [], []
    for raw in (text or "").split(","):
        want = raw.strip().lower()
        if not want:
            continue
        squashed = re.sub(r"[^a-z0-9]", "", want)
        hit = None
        for s in ALL_SOURCES:
            names = {re.sub(r"[^a-z0-9]", "", s.key.lower()), re.sub(r"[^a-z0-9]", "", s.name.lower())}
            names |= {re.sub(r"[^a-z0-9]", "", part.strip().lower()) for part in s.name.split("/")}
            names.discard("")
            if squashed and (squashed in names
                             or any(len(n) >= 4 and (n in squashed or squashed in n) for n in names)):
                hit = s.key
                break
        (picked if hit else unknown).append(hit or raw.strip())
    return picked, unknown


def do_search(args, run_dir, log):
    countries = parse_countries(args.countries)
    if not args.no_remote and REMOTE not in countries:
        countries = countries + [REMOTE]
    ctx, user_years = build_context(args, log, countries)
    include, unknown_in = parse_platforms(args.sources)
    exclude, unknown_ex = parse_platforms(args.exclude_sources)
    for name in unknown_in + unknown_ex:
        log(f"platform {name!r} is not one this bot searches - `job_bot sources` lists them")
    sources = select_sources(include or None, exclude or None, remote=not args.no_remote)
    skipped = [s.key for s in ALL_SOURCES if s.needs_env and not s.enabled()]
    asked_off = [k for k in include if k not in {s.key for s in sources}]
    if asked_off:
        log(f"platforms picked but not set up (missing API key): {', '.join(asked_off)}")
    window = (f"{ctx.hours:g} hour(s)" if ctx.hours else (f"{ctx.days} day(s)" if ctx.days else "any age"))
    log(f"job_bot v{__version__} | roles={ctx.roles} | experience={args.experience} ({user_years}) | countries={countries}")
    log(f"posted within: {window}" + ("" if ctx.allow_undated else " (postings with no time on them are dropped)"))
    log(f"sources: {', '.join(s.key for s in sources)}" + (f" | keyed sources skipped (no API key): {', '.join(skipped)}" if skipped else ""))
    t0 = time.time()
    jobs, statuses = run_search(ctx, sources, log=log, workers=args.workers)
    if args.details:
        fetch_details(ctx, jobs, BY_KEY, limit=args.details, log=log)
    before = len(jobs)
    jobs = apply_fit_filter(jobs, args.fit)
    if before != len(jobs):
        log(f"fit filter ({args.fit}): {before} -> {len(jobs)} jobs")
    jobs = sort_jobs(jobs)
    plan = fallback_queries(ctx.roles, [c for c in countries if c != REMOTE], user_years)
    meta = {
        "run_id": os.path.basename(run_dir), "version": __version__,
        "roles": ctx.roles, "experience_label": args.experience or "", "experience_years": user_years,
        "countries": [c for c in countries if c != REMOTE], "remote": not args.no_remote,
        "days": args.days, "hours": ctx.hours, "window_hours": ctx.window_hours,
        "platforms": [s.key for s in sources], "platforms_asked": include,
        "fit_mode": args.fit, "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "seconds": round(time.time() - t0, 1), "requests": ctx.http.requests_made,
        "fallback_queries": len(plan), "resume_name": "", "resume_path": "",
    }
    with open(os.path.join(run_dir, "fallback_plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    save_run(run_dir, meta, statuses, jobs)
    log(f"search finished in {meta['seconds']}s using {meta['requests']} requests; fallback plan: {len(plan)} web-search queries -> fallback_plan.json")
    return meta, statuses, jobs


def do_score(run_dir, meta, jobs, resume_path, log):
    try:
        text = extract_text(resume_path)
    except ResumeError as e:
        log(f"resume error: {e}")
        return None
    info = score_jobs(jobs, text)
    meta["resume_name"] = os.path.basename(resume_path)
    meta["resume_path"] = os.path.abspath(os.path.expanduser(resume_path))
    meta["resume_skills"] = info["resume_skills"]
    log(f"score: {info['scored']} jobs scored against {meta['resume_name']} ({info['resume_chars']} chars, "
        f"{len(info['resume_skills'])} skills detected: {', '.join(info['resume_skills'][:15])}{'…' if len(info['resume_skills']) > 15 else ''})")
    return info


def latest_run_dir(root=None):
    """The newest run under ~/Documents/JobHunt (or `root`), or None."""
    root = os.path.abspath(os.path.expanduser(root or DEFAULT_OUT_ROOT))
    if not os.path.isdir(root):
        return None
    runs = [os.path.join(root, d) for d in os.listdir(root)
            if os.path.isfile(os.path.join(root, d, "run.json"))]
    return max(runs, key=os.path.getmtime) if runs else None


def apply_like_last(args, log):
    """Fill --role/--experience/--countries/--resume from the newest run."""
    last = latest_run_dir(args.out_root)
    if not last:
        raise SystemExit("--like-last: no earlier run found under " + os.path.abspath(os.path.expanduser(args.out_root or DEFAULT_OUT_ROOT)))
    _, meta, _, _ = load_run(last)
    args.role = args.role or list(meta.get("roles") or [])
    args.experience = args.experience or meta.get("experience_label") or None
    if not args.countries and meta.get("countries"):
        args.countries = ",".join(meta["countries"])
    # India is always part of the search (same rule as the phone and jobhunt.yml).
    if args.countries and "IN" not in [c.strip().upper() for c in args.countries.split(",")] \
            and "india" not in args.countries.lower():
        args.countries = "IN," + args.countries
    if not getattr(args, "resume", None) and meta.get("resume_path") and os.path.exists(meta["resume_path"]):
        args.resume = meta["resume_path"]
    if getattr(args, "hours", None) is None and meta.get("hours"):
        args.hours = meta["hours"]
    if not getattr(args, "sources", None) and meta.get("platforms_asked"):
        args.sources = ",".join(meta["platforms_asked"])
    log(f"like-last: roles={args.role} experience={args.experience} countries={args.countries} resume={os.path.basename(args.resume or '') or '-'} (from {os.path.basename(last)})")
    return args


def apply_limit(args):
    """--limit, else NAUKRI_APPLY_LIMIT (set per task by the scheduler)."""
    if getattr(args, "limit", None) is not None:
        return args.limit
    raw = os.environ.get("NAUKRI_APPLY_LIMIT", "").strip()
    return int(raw) if raw.isdigit() else None


def do_apply(run_dir, meta, statuses, jobs, args, log):
    from jobbot import autoapply
    try:
        autoapply.load_naukri()
    except autoapply.ApplierUnavailable as e:
        log(f"apply: {e}")
        return None
    limit = apply_limit(args)
    dry = not getattr(args, "yes", False)
    cards = autoapply.linkedin_cards(jobs, min_score=getattr(args, "min_score", None))
    web = autoapply.web_postings(jobs, min_score=getattr(args, "min_score", None))
    log(f"apply: {len(cards)} LinkedIn + {len(web)} company-site / other-board posting(s) in this run{'' if limit is None else f', at most {limit} this run'}{' (dry run - add --yes to send)' if dry else ''}")
    outcomes = autoapply.apply_run(jobs, per_run=limit, dry_run=dry, min_score=getattr(args, "min_score", None))
    marked = autoapply.mark_jobs(jobs, outcomes)
    if marked:
        save_run(run_dir, meta, statuses, jobs)
        render(run_dir, meta, jobs, statuses)
    text = autoapply.summarise(outcomes)
    if text:
        for line in text.strip("\n").splitlines():
            log(line.strip())
    return outcomes


def do_contacts(run_dir, meta, statuses, jobs, log):
    """Recruiters / hiring managers per company -> contacts.json and each job's extra.contacts."""
    from jobbot import contacts
    from jobbot.http import Http
    try:
        found = contacts.enrich(jobs, Http(log=log), meta.get("roles") or [], log=log)
    except Exception as e:  # noqa: BLE001 - contacts are a bonus, never the reason a run fails
        log(f"contacts: skipped ({e})")
        return None
    with open(os.path.join(run_dir, "contacts.json"), "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=1)
    contacts.attach(jobs, found)
    meta["contacts"] = {"companies": len(found), "providers": contacts.providers()}
    save_run(run_dir, meta, statuses, jobs)
    return found


def cmd_run(args):
    log0 = Logger(None, quiet=args.quiet)
    if getattr(args, "like_last", False):
        apply_like_last(args, log0)
    if not args.role:
        raise SystemExit("--role is required (or --like-last)")
    run_dir = make_run_dir(args)
    log = Logger(os.path.join(run_dir, "run.log"), quiet=args.quiet)
    meta, statuses, jobs = do_search(args, run_dir, log)
    if args.resume:
        do_score(run_dir, meta, jobs, args.resume, log)
        jobs = sort_jobs(jobs)
        save_run(run_dir, meta, statuses, jobs)
    if not getattr(args, "no_contacts", False):
        do_contacts(run_dir, meta, statuses, jobs, log)
    report = render(run_dir, meta, jobs, statuses)
    summary(meta, jobs, statuses, report, log)
    if getattr(args, "apply_found", False):
        do_apply(run_dir, meta, statuses, jobs, args, log)
    print(json.dumps({"run_dir": run_dir, "report": report, "jobs": len(jobs), "fallback_plan": os.path.join(run_dir, "fallback_plan.json")}))
    if args.open:
        open_report(report)


def cmd_apply(args):
    run_dir = args.run or latest_run_dir(args.out_root)
    if not run_dir:
        raise SystemExit("no run found; pass --run <dir>")
    run_dir, meta, statuses, jobs = load_run(run_dir)
    log = Logger(os.path.join(run_dir, "run.log"), quiet=args.quiet)
    outcomes = do_apply(run_dir, meta, statuses, jobs, args, log)
    if outcomes is None:
        sys.exit(2)
    summary_ = outcomes.get("_summary", {})
    print(json.dumps({"run_dir": run_dir, "report": os.path.join(run_dir, "report.html"),
                      "linkedin": summary_.get("linkedin", {}), "dry_run": summary_.get("dry_run", True),
                      "pending_questions": summary_.get("pending_questions", 0)}))


def cmd_search(args):
    run_dir = make_run_dir(args)
    log = Logger(os.path.join(run_dir, "run.log"), quiet=args.quiet)
    meta, statuses, jobs = do_search(args, run_dir, log)
    report = render(run_dir, meta, jobs, statuses)
    summary(meta, jobs, statuses, report, log)
    print(json.dumps({"run_dir": run_dir, "report": report, "jobs": len(jobs)}))


def cmd_score(args):
    run_dir, meta, statuses, jobs = load_run(args.run)
    log = Logger(os.path.join(run_dir, "run.log"), quiet=args.quiet)
    if do_score(run_dir, meta, jobs, args.resume, log) is None:
        sys.exit(2)
    jobs = sort_jobs(jobs)
    save_run(run_dir, meta, statuses, jobs)
    report = render(run_dir, meta, jobs, statuses)
    summary(meta, jobs, statuses, report, log)
    print(json.dumps({"run_dir": run_dir, "report": report, "jobs": len(jobs)}))
    if args.open:
        open_report(report)


def cmd_render(args):
    run_dir, meta, statuses, jobs = load_run(args.run)
    report = render(run_dir, meta, sort_jobs(jobs), statuses)
    print(json.dumps({"run_dir": run_dir, "report": report, "jobs": len(jobs)}))
    if args.open:
        open_report(report)


def cmd_merge(args):
    run_dir, meta, statuses, jobs = load_run(args.run)
    log = Logger(os.path.join(run_dir, "run.log"), quiet=args.quiet)
    items = load_extra_file(args.file)
    added = merge_extra(jobs, items, meta.get("experience_years"))
    log(f"merge: {added} new jobs added from {args.file} ({len(items)} items read)")
    statuses.append({"source": "web", "source_name": "Web search (fallback)", "country": "*", "status": "ok", "count": added, "seconds": 0})
    resume = args.resume or meta.get("resume_path")
    if resume and os.path.exists(resume):
        do_score(run_dir, meta, jobs, resume, log)
    jobs = sort_jobs(jobs)
    save_run(run_dir, meta, statuses, jobs)
    report = render(run_dir, meta, jobs, statuses)
    summary(meta, jobs, statuses, report, log)
    print(json.dumps({"run_dir": run_dir, "report": report, "jobs": len(jobs), "added": added}))
    if args.open:
        open_report(report)


def cmd_fallback_queries(args):
    if args.run:
        run_dir, meta, _, _ = load_run(args.run)
        plan = fallback_queries(meta.get("roles", []), meta.get("countries", []), meta.get("experience_years"))
    else:
        plan = fallback_queries(args.role or [], parse_countries(args.countries), parse_user_experience(args.experience))
    if args.platforms:
        keep = {p.strip() for p in args.platforms.split(",")}
        plan = [q for q in plan if q["platform"] in keep]
    print(json.dumps(plan, ensure_ascii=False, indent=1))


def cmd_sources(args):
    from jobbot import sites
    listed = sites.load()
    print(f"{'key':<14} {'name':<28} {'on':<5} {'ready':<6} {'scope':<28} note")
    for s in ALL_SOURCES:
        scope = "remote boards" if s.remote_only else ("all countries" if s.countries is None else ", ".join(s.countries))
        note = sites.note(s.key) or (("needs " + ", ".join(s.needs_env)) if s.needs_env else
                                     ("client-side keyword filter" if not s.searchable else ""))
        on = listed.get(s.key, {"on": True})["on"]
        print(f"{s.key:<14} {s.name:<28} {'yes' if on else 'OFF':<5} {'yes' if s.enabled() else 'no':<6} {scope[:28]:<28} {note[:70]}")
    print(f"\nSwitch a platform off for good in {sites.DEFAULT_PATH}; --sources picks them for one run.")
    stray = sites.unknown_keys([s.key for s in ALL_SOURCES])
    if stray:
        print("in that file but unknown here (typo?): " + ", ".join(stray))
    print("\nBlocked for scripts (direct links + web-search fallback only): Indeed, Glassdoor, Naukri, StepStone, Hirist, Jobly, CareerCross, GaijinPot, Nationale Vacaturebank")


def cmd_countries(args):
    print(f"{'code':<5} {'name':<22} aliases")
    for code, m in COUNTRIES.items():
        mark = "*" if code in DEFAULT_COUNTRIES else " "
        print(f"{code:<4}{mark} {m['name']:<22} {', '.join(m['aliases'])}")
    print("\n* = default set. Add REMOTE automatically unless --no-remote.")


def cmd_selftest(args):
    log = Logger(None, quiet=False)
    countries = parse_countries(args.countries) if args.countries else ["DE", "NL", "ES", "FI", "AU", "JP", "TH", "IN", REMOTE]
    args.role = args.role or ["python developer"]
    args.days, args.max_per_source, args.exclude, args.must, args.loose = 30, 15, "", "", False
    ctx, _ = build_context(args, log, countries)
    sources = select_sources(None, None, remote=True)
    jobs, statuses = run_search(ctx, sources, log=log, workers=args.workers)
    ok = sum(1 for s in statuses if s["status"] == "ok")
    print(json.dumps({"tasks": len(statuses), "ok": ok, "jobs": len(jobs),
                      "failed": [f"{s['source']}:{s['country']} {s['status']} {s.get('error', '')}" for s in statuses if s["status"] != "ok"]}, indent=1))


# ----------------------------------------------------------------------------- argparse
def add_search_args(p):
    p.add_argument("--role", "-r", action="append", help="job title / role to search (repeatable)")
    p.add_argument("--experience", "-e", help="your years of experience, e.g. 3 or 2-4")
    p.add_argument("--countries", "-c", help="comma list of countries (names or ISO2). Default: " + ",".join(DEFAULT_COUNTRIES))
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help="ignore postings older than N days (0 = no limit)")
    p.add_argument("--hours", type=float, default=None, metavar="N",
                   help="ignore postings older than N hours - wins over --days. Under 24 h, a posting the "
                        "board gave no time for is dropped (it cannot be shown to be inside the window); "
                        "--allow-undated keeps those")
    p.add_argument("--allow-undated", action="store_true", dest="allow_undated",
                   help="with --hours: keep postings whose exact time the board never said")
    p.add_argument("--max-per-source", type=int, default=DEFAULT_MAX_PER_SOURCE, help="cap per source per country")
    p.add_argument("--details", type=int, default=DEFAULT_DETAILS, help="fetch full descriptions for the top N jobs (0 = off)")
    p.add_argument("--sources", "--platforms", dest="sources",
                   help="only these platforms (comma list of keys or names, e.g. linkedin,seek,\"The Muse\"; "
                        "see `sources`). Default: every platform that is set up")
    p.add_argument("--exclude-sources", help="skip these platforms (comma list of keys or names)")
    p.add_argument("--exclude", help="drop jobs whose title contains any of these terms (comma list)")
    p.add_argument("--must", help="keep only jobs whose title contains all of these terms (comma list)")
    p.add_argument("--loose", action="store_true", help="do not drop platform results that never mention the role words")
    p.add_argument("--min-relevance", type=float, default=0.4, dest="min_relevance", metavar="0..1",
                   help="how closely a job TITLE must match the role (default 0.4). Raise it for fewer, "
                        "closer results; --loose turns the check off")
    p.add_argument("--no-remote", action="store_true", help="skip remote job boards / the Remote tab")
    p.add_argument("--fit", choices=["default", "strict", "all"], default="default",
                   help="experience filter: default drops clear mismatches, strict keeps only fits, all keeps everything")
    p.add_argument("--out", help="run directory (default: ~/Documents/JobHunt/<date>_<role>)")
    p.add_argument("--out-root", help="parent directory for auto-named runs")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--interval", type=float, default=0.8, help="minimum seconds between requests to the same host")
    p.add_argument("--quiet", action="store_true")


def cmd_wizard(args=None):
    """Interactive mode: used when the bot is started with no arguments (e.g. double-clicking jobhunt.bat)."""
    print(f"Job Hunt bot v{__version__} - answer a few questions (press Enter for the default)\n")

    def ask(q, default=""):
        try:
            v = input(f"{q}{' [' + default + ']' if default else ''}: ").strip()
        except EOFError:
            v = ""
        return v or default

    role = ask("Job title / role (comma-separate several)")
    while not role:
        role = ask("Job title / role is required")
    exp = ask("Your years of experience (e.g. 3 or 2-4)")
    countries = ask("Countries", ",".join(DEFAULT_COUNTRIES))
    resume = ask("Resume file for the match score (optional - drag the file here)").strip().strip('"').strip("'")
    window = ask("Posted within (e.g. 2h, 12h, 7d)", f"{DEFAULT_DAYS}d")
    platforms = ask("Platforms (comma list, or Enter for all)", "all")
    argv = ["run", "--countries", countries, "--open"]
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([hd]?)\s*", window, re.I)
    if m and m.group(2).lower() == "h":
        argv += ["--hours", m.group(1)]
    else:
        argv += ["--days", str(int(float(m.group(1)))) if m else str(DEFAULT_DAYS)]
    if platforms and platforms.lower() not in ("all", "any", "*"):
        argv += ["--sources", platforms]
    for r in role.split(","):
        if r.strip():
            argv += ["--role", r.strip()]
    if exp:
        argv += ["--experience", exp]
    if resume:
        argv += ["--resume", resume]
    print("\nSearching... this usually takes 3-8 minutes.\n")
    main(argv)


def main(argv=None):
    # API keys come from .env when they are not already in the environment, so
    # the keyed sources work the same on the PC and in GitHub Actions.
    load_env()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return cmd_wizard()
    ap = argparse.ArgumentParser(prog="job_bot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"job_bot {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("wizard", help="interactive mode (same as running with no arguments)").set_defaults(fn=cmd_wizard)

    p = sub.add_parser("run", help="search + score + render (+ apply with --apply-found)")
    add_search_args(p)
    p.add_argument("--resume", help="resume file (.pdf/.docx/.txt) used only for match scoring")
    p.add_argument("--no-contacts", action="store_true", dest="no_contacts",
                   help="skip the recruiter / hiring-manager lookup per company (SIGNALHIRE_API_KEY, HUNTER_API_KEY, APOLLO_API_KEY)")
    p.add_argument("--open", action="store_true", help="open the report in the browser")
    p.add_argument("--like-last", action="store_true", dest="like_last",
                   help="reuse the roles, experience, countries and resume of the newest run")
    p.add_argument("--apply-found", action="store_true", dest="apply_found",
                   help="after the search, apply to the LinkedIn postings (Easy Apply) through the "
                        "Naukri screener's applier; dry run unless --yes")
    p.add_argument("--yes", action="store_true", help="with --apply-found: really send applications")
    p.add_argument("--limit", type=int, metavar="N",
                   help="with --apply-found: at most N applications this run (default: NAUKRI_APPLY_LIMIT, else the daily cap)")
    p.add_argument("--min-score", type=float, dest="min_score",
                   help="with --apply-found: only postings scoring at least this against your resume")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("apply", help="apply to a run's LinkedIn postings (Easy Apply)")
    p.add_argument("--run", help="run directory (default: the newest run)")
    p.add_argument("--out-root", help="parent directory of runs, for the default")
    p.add_argument("--yes", action="store_true", help="really send applications (default is a dry run)")
    p.add_argument("--limit", type=int, metavar="N", help="at most N applications this run")
    p.add_argument("--min-score", type=float, dest="min_score", help="only postings scoring at least this")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("search", help="search only")
    add_search_args(p)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("score", help="score an existing run against a resume")
    p.add_argument("--run", required=True)
    p.add_argument("--resume", required=True)
    p.add_argument("--open", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("render", help="rebuild report.html")
    p.add_argument("--run", required=True)
    p.add_argument("--open", action="store_true")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("merge", help="merge extra jobs (JSON list) into a run")
    p.add_argument("--run", required=True)
    p.add_argument("--file", required=True, help="JSON list of {title, company, url, country, location, source, snippet, posted}")
    p.add_argument("--resume", help="re-score with this resume (defaults to the run's resume)")
    p.add_argument("--open", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_merge)

    p = sub.add_parser("fallback-queries", help="web-search plan for blocked platforms")
    p.add_argument("--run", help="existing run directory (uses its roles/countries)")
    p.add_argument("--role", "-r", action="append")
    p.add_argument("--experience", "-e")
    p.add_argument("--countries", "-c")
    p.add_argument("--platforms", help="comma list of platform keys to include (indeed,glassdoor,naukri,stepstone,hirist,...)")
    p.set_defaults(fn=cmd_fallback_queries)

    p = sub.add_parser("sources", help="list sources")
    p.set_defaults(fn=cmd_sources)
    p = sub.add_parser("countries", help="list countries")
    p.set_defaults(fn=cmd_countries)

    p = sub.add_parser("selftest", help="connectivity check of all sources")
    p.add_argument("--role", "-r", action="append")
    p.add_argument("--experience", "-e", default="3")
    p.add_argument("--countries", "-c")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--interval", type=float, default=0.8)
    p.set_defaults(fn=cmd_selftest)

    args = ap.parse_args(argv)
    if args.cmd == "search" and not args.role:
        ap.error("--role is required (e.g. --role \"python developer\")")
    if args.cmd == "run" and not args.role and not getattr(args, "like_last", False):
        ap.error("--role is required (e.g. --role \"python developer\"), or --like-last")
    args.fn(args)


if __name__ == "__main__":
    main()
