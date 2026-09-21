#!/usr/bin/env python
"""careers_bot - search company career pages directly (the companies in job-hunt/assets/companies.txt).

Job boards like LinkedIn miss a lot; companies post everything on their own career page first. This reads
those pages through the public job-board APIs they are built on, keeps the postings that match your role,
experience range and countries, checks whether each one offers relocation / visa sponsorship, and scores
it against your resume.

  python careers_bot.py run --role "software engineer" --experience 3-5 --countries worldwide --relocation strict --resume cv.pdf
  python careers_bot.py check                  is every company in the list still answering?
  python careers_bot.py find agoda "booking"   which job board does a company use? (prints lines to paste into the list)
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from jobbot import __version__  # noqa: E402
from jobbot.careers import geo  # noqa: E402
from jobbot.careers import resolve as resolver  # noqa: E402
from jobbot.careers.ats import Unresolved, fetch, probe  # noqa: E402
from jobbot.careers.companies import ATS_TYPES, DEFAULT_PATH, Company, load, select  # noqa: E402
from jobbot.careers.relocation import assess, excerpt_for_model, merge_opinion  # noqa: E402
from jobbot import localai  # noqa: E402
from jobbot.config import REMOTE  # noqa: E402
from jobbot.experience import parse_experience, seniority_from_title  # noqa: E402
from jobbot.http import Http  # noqa: E402
from jobbot.resume import ResumeError, extract_text  # noqa: E402
from jobbot.scoring import score_jobs  # noqa: E402
from jobbot.sources.base import SearchContext  # noqa: E402
from jobbot.textutil import slugify  # noqa: E402

FIT_WEIGHT = {"fit": 1.0, "unknown": 0.7, "over": 0.6, "stretch": 0.5, "no": 0.1}
RELOC_WEIGHT = {"yes": 1.0, "visa": 0.85, "maybe": 0.6, "unknown": 0.4, "no": 0.1}
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EMAIL_SKIP = re.compile(r"privacy|gdpr|dpo|data|protect|accommodat|accessib|legal|fraud|noreply|no-reply|security|press|media", re.I)
# Career pages list every job in the company. A generic role like "software engineer" would otherwise pull in
# "Sales Engineer", "Engineering Manager", "Support Engineer"... These words are dropped unless your role has them.
NOT_THE_ROLE = ["support", "sales", r"solutions?\s+(?:engineer|architect|consultant)", "customer", "success", r"accounts?",
                r"recruit\w*", "talent", "marketing",
                r"partner\w*", "field", "pre-?sales", "consultant", "manager", "director", "head of", "vp", "vice president",
                "intern", "internship", "working student", "werkstudent", "trainee", "apprentice"]


HEADER = """# Companies whose career pages the careers bot reads (phone page -> Careers tab, or careers_bot.py).
#
# One company per line:   Name | ats | board | note
#
#   ats     greenhouse | lever | ashby | smartrecruiters | workable | recruitee | workday
#           auto  = find the board on the first run (and remember it in assets/boards_cache.json)
#           link  = no public API; the note holds the careers URL to apply through
#   board   the company's id on that job board:
#             greenhouse       job-boards.greenhouse.io/<board>      e.g. agoda
#             lever            jobs.lever.co/<board>                 e.g. binance
#             ashby            jobs.ashbyhq.com/<board>              e.g. openai
#             smartrecruiters  jobs.smartrecruiters.com/<board>      e.g. grab
#             workable         apply.workable.com/<board>
#             recruitee        <board>.recruitee.com                 e.g. bunq
#             workday          <host>/<tenant>/<site> from the careers URL
#                              e.g. nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite
#   note    free text shown on the phone - and, if you paste a careers URL here, the link
#           this bot uses. A link to a known job board wins over the ats/board columns, so
#           pasting https://jobs.ashbyhq.com/openai is enough to pin a company for good.
#
# A row whose board stops answering is not lost: careers_bot re-resolves it (link -> the
# company's careers page -> name variants across every board API -> the local model, each
# one verified) and caches what works. Nothing here has to be right for the search to run.
#
#   python job-hunt/scripts/careers_bot.py resolve            check every row, print what is wrong
#   python job-hunt/scripts/careers_bot.py resolve --write    fix this file from what answered
#   python job-hunt/scripts/careers_bot.py find "<company>"   which board does one company use?
"""


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def parse_range(value):
    """'3-5' -> (3, 5); '4' -> (4, 4); '5+' -> (5, 8); '' -> (None, None)"""
    s = (value or "").strip().lower()
    m = re.match(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", s)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        return lo, hi
    m = re.match(r"(\d+(?:\.\d+)?)\s*\+", s)
    if m:
        return float(m.group(1)), float(m.group(1)) + 3
    m = re.match(r"(\d+(?:\.\d+)?)", s)
    return (float(m.group(1)), float(m.group(1))) if m else (None, None)


def parse_countries(text):
    """-> set of ISO2 codes, or None for worldwide."""
    out, unknown = set(), []
    for part in re.split(r"[,;]", text or ""):
        if not part.strip():
            continue
        code = geo.resolve(part)
        if code == "*":
            return None
        if code:
            out.add(code)
        else:
            unknown.append(part.strip())
    if unknown:
        log(f"warning: unknown countries ignored: {', '.join(unknown)}")
    return out or None


def fit_for_range(lo, hi, jmin, jmax, seniority):
    """fit / stretch / over / no / unknown for someone with lo..hi years against a posting asking jmin..jmax."""
    if lo is None:
        return "unknown"
    if jmin is None and jmax is None and seniority:
        if seniority[0] == "intern":
            return "over" if lo > 1 else "fit"
        jmin, jmax = seniority[1]
    if jmin is None and jmax is None:
        return "unknown"
    jmin = jmin or 0
    if jmin > hi:
        return "stretch" if jmin - hi <= 2 else "no"
    if jmax is not None and jmax + 2 < lo:
        return "over"
    return "fit"


def second_opinions(relevant, ctx, want, a, lo, hi, log):
    """Let the local model read the postings the patterns could not settle.

    Only postings that would otherwise be kept (fresh, wanted country, fit)
    and are labelled maybe / unknown, best relevance first, at most
    LOCAL_AI_RELOC_MAX and at most 40% of the model's time budget - the
    "why it fits" lines need the rest.
    """
    if not localai.available("llm") or a.relocation == "any":
        return 0
    cap = int(os.environ.get("LOCAL_AI_RELOC_MAX") or 40)
    reserve = localai.budget_left() * 0.6
    todo = [j for j in relevant
            if j.extra["reloc"]["label"] in ("maybe", "unknown") and ctx.fresh(j.posted)
            and (want is None or set(j.extra["countries"]) & want)
            and not ((a.fit == "strict" and j.fit != "fit") or (a.fit == "default" and j.fit == "no"))]
    todo.sort(key=lambda j: -(j.relevance or 0))
    asked = upgraded = 0
    for j in todo[:cap]:
        if localai.budget_left() <= reserve:
            break
        opinion = localai.relocation_opinion(j.title, excerpt_for_model(j.title, j.description))
        asked += 1
        if not opinion:
            continue
        before = j.extra["reloc"]["label"]
        j.extra["reloc"] = merge_opinion(j.extra["reloc"], opinion, j.description)
        if j.extra["reloc"]["label"] != before:
            upgraded += 1
    if asked:
        log(f"relocation: {asked} second opinion(s) from the local model, {upgraded} label(s) changed")
    return upgraded


def summarize_top(jobs, resume_text, log):
    """One "why it fits / gap" line per top job from the local model (budgeted)."""
    if not localai.available("llm"):
        return 0
    top = int(os.environ.get("LOCAL_AI_SUMMARY_TOP") or 30)
    done = 0
    for j in jobs[:top]:
        if localai.budget_left() < 15:
            break
        out = localai.summarize_fit(resume_text, j.title, j.description, j.matched_skills, j.missing_skills)
        if out:
            j.extra["ai_summary"] = out
            done += 1
    if jobs:
        log(f"local AI: {done} of {min(top, len(jobs))} top jobs got a fit line ({localai.budget_left():.0f}s of budget left)")
    return done


def chance(job):
    """0-100: how likely this one turns into an offer - resume match, experience fit and relocation support."""
    match = job.score / 100.0 if job.score is not None else 0.35 + 0.3 * job.relevance
    return round(100 * (0.5 * match + 0.25 * FIT_WEIGHT.get(job.fit, 0.5) + 0.25 * RELOC_WEIGHT[job.extra["reloc"]["label"]]))


_NOT_A_CITY = re.compile(r"^(?:remote|hybrid|anywhere|worldwide|global|asia|europe|emea|apac|latam|americas|south ?east asia|"
                         r"middle east|usa?|uk|uae)$", re.I)
_COUNTRY_NAMES = {n.lower() for n in geo.NAMES.values()}


def city_of(location):
    """First real city in a location string: 'Taiwan, Taipei / Thailand, Bangkok' -> 'Taipei'."""
    for seg in re.split(r" / |;| or ", location or ""):
        for part in re.sub(r"\(.*?\)", "", seg).split(","):
            p = re.sub(r"^(?:hybrid|remote|on-?site)\s*[-–:]\s*", "", part.strip(), flags=re.I)
            if p and not _NOT_A_CITY.match(p) and p.lower() not in _COUNTRY_NAMES and not re.fullmatch(r"[A-Z]{2}", p):
                return p
    return ""


def make_resolver(http, cache, use_ai=True, lock=None):
    """The callback fetch() uses when a board does not answer: find the real one, once, per company.

    A stale slug used to cost a company its whole row. Now the row is re-resolved (link ->
    careers page -> name -> local AI -> LinkedIn link) and the answer is cached on disk, so
    the fix is paid for once and every later run starts from the working board.
    """
    def fix(c, why):
        with (lock or _NOLOCK):
            hit = resolver.cached(cache, c.name.lower())
        if not hit:
            hit = resolver.resolve(http, c.name, c.url, c.note, use_ai=use_ai, cache=None, log=None,
                                   hint_ats=c.ats if c.ats in ATS_TYPES else "",
                                   hint_board=c.board if c.board and c.ats in ATS_TYPES else "")
            with (lock or _NOLOCK):
                cache[c.name.lower()] = hit
        if not hit.get("ats"):
            # The status line below already says "link" and where to apply: no second line here.
            c.resolved = hit.get("via", "")
            c.url = hit.get("url") or c.url
            return None
        fixed = Company(c.name, hit["ats"], hit["board"], c.note, hit.get("url") or c.url,
                        resolved=hit.get("via", ""), line=c.line)
        if (fixed.ats, fixed.board) != (c.ats, c.board):
            log(f"  {c.name:<18} board fixed: {c.ats or '-'}/{c.board or '-'} -> {fixed.ats}/{fixed.board}"
                f"  (via {fixed.resolved}; {why})")
        c.ats, c.board, c.url, c.resolved = fixed.ats, fixed.board, fixed.url, fixed.resolved
        return fixed
    return fix


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_NOLOCK = _NullLock()


def search_companies(companies, keep, roles, details, workers, place=None, use_ai=True, cache=None):
    http = Http(log=log, min_interval=0.35)
    statuses, jobs, recruiters = {}, [], {}
    cache = load_cache() if cache is None else cache
    fix = make_resolver(http, cache, use_ai=use_ai, lock=threading.Lock())

    def work(c):
        t0 = time.time()
        try:
            found, total, people = fetch(http, c, keep, roles, details, place, resolver=fix)
            return c, found, dict(status="ok", total=total, kept=len(found), seconds=round(time.time() - t0, 1),
                                  resolved=c.resolved), people
        except Unresolved as e:
            return c, [], dict(status="link", total=0, kept=0, seconds=round(time.time() - t0, 1),
                               resolved=e.via, error=f"no job-board API; apply through {e.url}", url=e.url), []
        except Exception as e:  # noqa: BLE001 - one broken board must not stop the run
            return c, [], dict(status="error", total=0, kept=0, seconds=round(time.time() - t0, 1),
                               resolved=c.resolved, error=f"{type(e).__name__}: {str(e)[:160]}"), []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(work, c) for c in companies]):
            c, found, st, people = fut.result()
            statuses[c.name] = st
            recruiters[c.name] = people
            jobs.extend(found)
            log(f"  {c.name:<18} {c.ats:<15} {st['status']:<6} {st['kept']:>4} of {st['total']:>4} match the role  {st['seconds']}s"
                + (f"  ({st['error']})" if st.get("error") else ""))
    save_cache(cache)
    return jobs, statuses, recruiters, http.requests_made


def load_cache():
    return resolver.load_cache()


def save_cache(cache):
    resolver.save_cache(cache)


def cmd_run(a):
    t0 = time.time()
    roles = [r.strip() for r in ",".join(a.role).split(",") if r.strip()]
    lo, hi = parse_range(a.experience)
    want = parse_countries(a.countries)
    companies = select(load(a.companies_file, log=log), a.companies)
    if not companies:
        raise SystemExit(f"no companies match '{a.companies}' in {a.companies_file or DEFAULT_PATH}")
    ctx = SearchContext(roles, [], days=a.days,
                        exclude_terms=[t.strip() for t in (a.exclude or "").split(",") if t.strip()],
                        must_terms=[t.strip() for t in (a.must or "").split(",") if t.strip()])

    role_text = " ".join(roles).lower()
    not_role = [w for w in NOT_THE_ROLE if not re.search(r"\b" + w + r"\b", role_text)]
    not_role_rx = re.compile(r"\b(?:" + "|".join(not_role) + r")\b", re.I) if not_role else None

    def keep(title):
        # "(Bangkok based, Relocation Support)" / "[EM]" are about the job, not the role: ignore them here
        core = re.sub(r"\(.*?\)|\[.*?\]|relocation\s+\w+", " ", title or "", flags=re.I)
        return (bool(title) and not (not_role_rx and not_role_rx.search(core)) and not ctx.excluded(title)
                and ctx.relevance(title) >= 0.7)

    def place(codes):
        return want is None or not codes or bool(set(codes) & want)

    log(localai.status_line())
    log(f"careers_bot v{__version__} | roles={roles} | experience={a.experience or '-'} ({lo}-{hi}) | "
        f"countries={'worldwide' if want is None else sorted(want)} | relocation={a.relocation} | {len(companies)} companies")
    found, statuses, recruiters, requests = search_companies(companies, keep, roles, a.details, a.workers, place,
                                                             use_ai=not a.no_ai_boards)

    # Postings that only say "Hybrid" fall back to the company's hub when its note names exactly one country.
    hubs = {c.name: geo.codes(c.note) for c in companies}
    seen, relevant = set(), []
    for j in found:
        if j.id in seen:
            continue
        seen.add(j.id)
        if not j.extra["countries"] and len(hubs.get(j.company) or []) == 1:
            j.extra["countries"] = list(hubs[j.company])
            j.country = j.extra["countries"][0]
        j.relevance = ctx.relevance(j.title)
        jmin, jmax = parse_experience(j.title + ". " + j.description)
        sen = seniority_from_title(j.title)
        j.exp_min, j.exp_max, j.seniority = jmin, jmax, (sen[0] if sen else "")
        j.fit = fit_for_range(lo, hi, jmin, jmax, sen)
        j.extra["reloc"] = assess(j.title, j.description)
        relevant.append(j)

    second_opinions(relevant, ctx, want, a, lo, hi, log)
    reloc_yes = Counter(j.company for j in relevant if j.extra["reloc"]["label"] == "yes")
    reloc_seen = Counter(j.company for j in relevant)
    drops = Counter()
    jobs = []
    for j in relevant:
        codes = j.extra["countries"]
        if not ctx.fresh(j.posted):
            drops["older than %d days" % a.days] += 1
        elif want is not None and not (set(codes) & want):
            drops["other countries"] += 1
        elif (a.fit == "strict" and j.fit != "fit") or (a.fit == "default" and j.fit == "no"):
            drops["experience does not fit"] += 1
        elif a.relocation == "strict" and j.extra["reloc"]["label"] != "yes":
            drops["no relocation offered"] += 1
        elif a.relocation == "visa" and j.extra["reloc"]["label"] not in ("yes", "visa"):
            drops["no relocation or visa offered"] += 1
        else:
            jobs.append(j)
    log(f"filter: {len(relevant)} postings match the role, kept {len(jobs)}"
        + ("; dropped " + ", ".join(f"{n} {why}" for why, n in drops.most_common()) if drops else ""))

    resume_skills = []
    if a.resume:
        try:
            resume_text = extract_text(a.resume)
            info = score_jobs(jobs, resume_text) if jobs else {"resume_skills": []}
            resume_skills = info["resume_skills"][:25]
            log(f"score: {len(jobs)} jobs scored against your resume"
                + ("; semantic match on" if info.get("semantic") else ""))
            for j in jobs:
                j.extra["chance"] = chance(j)
            jobs.sort(key=lambda j: (-j.extra["chance"], -(j.score or 0)))
            summarize_top(jobs, resume_text, log)
        except ResumeError as e:
            log(f"resume error: {e} (jobs are not scored)")
    for j in jobs:
        j.extra["chance"] = chance(j)
    jobs.sort(key=lambda j: (-j.extra["chance"], -(j.score or 0)))

    by_company = {}
    for j in jobs:
        by_company.setdefault(j.company, []).append(j)
    out_companies = []
    for c in companies:
        st = statuses.get(c.name, {})
        mine = by_company.get(c.name, [])
        emails = []
        for j in mine:
            for e in _EMAIL.findall(j.description):
                e = e.strip(".").lower()
                if not _EMAIL_SKIP.search(e) and e not in emails:
                    emails.append(e)
        cities = [x for x, _ in Counter(city_of(j.location) for j in mine if city_of(j.location)).most_common(3)]
        out_companies.append({
            "name": c.name, "ats": c.ats, "careers": st.get("url") or c.careers, "note": c.note,
            "resolved": st.get("resolved", ""),
            "status": st.get("status", "skipped"), "error": st.get("error", ""),
            "open": st.get("total", 0), "role_matches": reloc_seen.get(c.name, 0), "shown": len(mine),
            "reloc_share": round(reloc_yes.get(c.name, 0) / reloc_seen[c.name], 2) if reloc_seen.get(c.name) else None,
            "cities": cities, "recruiters": recruiters.get(c.name, [])[:6], "emails": emails[:5],
        })

    codes_used = sorted({code for j in jobs for code in j.extra["countries"]})
    result = {
        "meta": {
            "version": __version__, "roles": roles, "experience": a.experience or "", "exp_range": [lo, hi],
            "countries": ["*"] if want is None else sorted(want), "relocation": a.relocation, "fit": a.fit, "days": a.days,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - t0, 1),
            "requests": requests, "companies": len(companies),
            "companies_ok": sum(1 for s in statuses.values() if s["status"] == "ok"),
            "companies_link_only": sum(1 for s in statuses.values() if s["status"] == "link"),
            "boards_fixed": sorted(n for n, s in statuses.items() if s.get("resolved") and s["status"] == "ok"),
            "role_matches": len(relevant), "dropped": dict(drops),
            "scored": any(j.score is not None for j in jobs), "resume_skills": resume_skills,
        },
        "names": {code: geo.name(code) for code in codes_used},
        "companies": out_companies,
        "jobs": [{
            "id": j.id, "title": j.title, "company": j.company, "url": j.url,
            "countries": j.extra["countries"], "location": j.location, "remote": j.remote, "posted": j.posted,
            "department": j.extra.get("department", ""), "type": j.employment_type,
            "exp": [j.exp_min, j.exp_max], "seniority": j.seniority, "fit": j.fit,
            "reloc": j.extra["reloc"]["label"], "visa": j.extra["reloc"]["visa"], "evidence": j.extra["reloc"]["evidence"],
            "score": j.score, "matched": j.matched_skills[:10], "missing": j.missing_skills[:6],
            "chance": j.extra["chance"], "recruiter": j.extra.get("recruiter", ""),
            "ai": j.extra.get("ai_summary"),
        } for j in jobs],
    }
    out = os.path.abspath(a.out or f"careers_{datetime.now().strftime('%Y-%m-%d_%H%M')}_{slugify(roles[0])[:30]}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    n_reloc = sum(1 for j in jobs if j.extra["reloc"]["label"] == "yes")
    log(f"RESULT: {len(jobs)} jobs ({n_reloc} with relocation) from {result['meta']['companies_ok']}/{len(companies)} companies "
        f"in {result['meta']['seconds']}s")
    for j in jobs[:8]:
        log(f"  {j.extra['chance']:>3}  {j.extra['reloc']['label']:<7} {j.fit:<8} {'/'.join(j.extra['countries'][:2]):<6} "
            f"{j.title[:52]:<52} @ {j.company}")
    print(json.dumps({"out": out, "jobs": len(jobs), "relocation": n_reloc, "companies": result["meta"]["companies_ok"]}))


def cmd_check(a):
    companies = select(load(a.companies_file, log=log), a.companies)
    _, statuses, _, _ = search_companies(companies, lambda t: False, ["engineer"], 0, a.workers,
                                         use_ai=not a.no_ai_boards)
    link = [n for n, s in statuses.items() if s["status"] == "link"]
    bad = [n for n, s in statuses.items() if s["status"] == "error" or (s["status"] == "ok" and not s["total"])]
    print(f"\n{len(companies) - len(bad) - len(link)}/{len(companies)} companies answer with open jobs"
          + (f"\n{len(link)} have no job-board API, only a link: {', '.join(sorted(link))}" if link else "")
          + (f"\ncheck these: {', '.join(sorted(bad))}" if bad else ""))
    return 1 if bad else 0


def cmd_resolve(a):
    """Check every row's board, find the right one where it is wrong, and write the list back."""
    companies = select(load(a.companies_file, log=log), a.companies)
    http = Http(log=log, min_interval=0.25)
    cache = {} if a.refresh else resolver.load_cache()
    lock = threading.Lock()
    fixed, link_only, same = [], [], 0

    def work(c):
        hit = resolver.cached(cache, c.name.lower())
        if hit is None:
            hint_ats = c.ats if c.ats in ATS_TYPES else ""
            hit = resolver.resolve(http, c.name, c.url, c.note, use_ai=not a.no_ai_boards, cache=None,
                                   hint_ats=hint_ats, hint_board=c.board if hint_ats else "")
            with lock:
                cache[c.name.lower()] = hit
        return c, hit

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for fut in as_completed([ex.submit(work, c) for c in companies]):
            c, hit = fut.result()
            if not hit.get("ats"):
                link_only.append((c, hit))
                log(f"  {c.name:<20} no board found      -> link {hit.get('url')}")
            elif (hit["ats"], hit["board"]) != (c.ats, c.board):
                fixed.append((c, hit))
                log(f"  {c.name:<20} {c.ats}/{c.board or '-'} -> {hit['ats']}/{hit['board']} "
                    f"({hit['jobs']} open, via {hit['via']})")
            else:
                same += 1
    resolver.save_cache(cache)
    print(f"\n{same} rows already correct, {len(fixed)} fixed, {len(link_only)} without a job-board API")
    for c, hit in sorted(fixed, key=lambda x: x[0].name.lower()):
        print(f"{c.name:<24} | {hit['ats']:<15} | {hit['board']:<45} | {c.note}")
    if a.write:
        n = rewrite_companies_file(a.companies_file or DEFAULT_PATH, companies, cache)
        print(f"\nwrote {n} readable rows to {a.companies_file or DEFAULT_PATH} (previous version kept as .bak)")
    elif fixed or link_only:
        print("\nrun again with --write to fold these into companies.txt")
    return 0


def rewrite_companies_file(path, companies, cache):
    """Write companies.txt from what actually answered: one row per company, boards that work.

    The old file is kept as <path>.bak. A company no board answered for stays in the list as a
    `link` row carrying its careers URL - it has no API to read, but the report still shows the
    company and a link to apply through, which a commented-out row would not.
    """
    import shutil
    from jobbot.careers.companies import Company as _C
    ok, link = [], []
    for c in companies:
        hit = cache.get(c.name.lower())
        # A checked company is written from what answered, including "nothing did": keeping the
        # row's old slug there is exactly how a dead board survives a cleanup.
        ats = hit.get("ats", "") if hit else (c.ats if c.readable else "")
        board = hit.get("board", "") if hit else (c.board if c.readable else "")
        hit = hit or {}
        (ok if ats and board else link).append((c, ats, board, hit.get("url") or c.url))
    lines = [HEADER.rstrip("\n"), "", "# ---- boards this bot reads through their public API"]
    for c, ats, board, url in sorted(ok, key=lambda x: x[0].name.lower()):
        # The link column is only worth the width when it is not the board's own URL.
        own = url if url and url != _C(c.name, ats, board).board_url else ""
        tail = " | ".join(x for x in (c.note, own) if x)
        lines.append(f"{c.name:<24} | {ats:<15} | {board:<58} | {tail}" if tail else f"{c.name:<24} | {ats:<15} | {board}")
    lines += ["", "# ---- no public job-board API: read as a link, apply on the company's own page",
              "#      (`careers_bot.py find \"<name>\"` again later - companies do move onto a board)"]
    for c, _ats, _board, url in sorted(link, key=lambda x: x[0].name.lower()):
        tail = " | ".join(x for x in (url or resolver.linkedin_search(c.name), c.note) if x)
        lines.append(f"{c.name:<24} | {'link':<15} | {'-':<58} | {tail}")
    if os.path.exists(path):
        shutil.copyfile(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(ok)


def cmd_find(a):
    """Which board does a company use? Prints a line ready to paste into companies.txt."""
    http = Http(log=log, min_interval=0.2)
    for name in a.names:
        url = name if name.lower().startswith("http") else ""
        hit = resolver.resolve(http, name if not url else url.split("//")[-1].split("/")[0], url,
                               use_ai=not a.no_ai_boards, log=log)
        if hit.get("ats"):
            print(f"{name:<20} | {hit['ats']:<15} | {hit['board']:<50} |   ({hit['jobs']} open, via {hit['via']})")
        else:
            print(f"# [no public job-board API] {name} | link | - | {hit['url']}")
        # Anything else that answers for the same name is worth knowing about.
        for slug in resolver.slug_variants(name, url)[:3]:
            for ats, n in probe(http, slug):
                if (ats, slug) != (hit.get("ats"), hit.get("board")):
                    print(f"{'  also':<20} | {ats:<15} | {slug:<50} |   ({n} open jobs)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="careers_bot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"careers_bot {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="search the career pages")
    p.add_argument("--role", "-r", action="append", required=True, help="job title (repeatable or comma-separated)")
    p.add_argument("--experience", "-e", help="your experience in years: 4, 3-5 or 5+")
    p.add_argument("--countries", "-c", default="worldwide", help="comma list of countries (names or ISO2), or worldwide")
    p.add_argument("--relocation", choices=["strict", "visa", "any"], default="any",
                   help="strict = only postings that offer relocation; visa = relocation or visa sponsorship; any = all")
    p.add_argument("--fit", choices=["default", "strict", "all"], default="default",
                   help="experience filter: default drops clear mismatches, strict keeps only fits, all keeps everything")
    p.add_argument("--days", type=int, default=0, help="only postings published in the last N days (0 = all open postings)")
    p.add_argument("--companies", help="only companies whose name contains one of these (comma list)")
    p.add_argument("--companies-file", help="company list (default: job-hunt/assets/companies.txt)")
    p.add_argument("--exclude", help="drop titles containing any of these terms (comma list)")
    p.add_argument("--must", help="keep only titles containing all of these terms (comma list)")
    p.add_argument("--resume", help="resume (.pdf/.docx/.txt) for the match score")
    p.add_argument("--details", type=int, default=120, help="full descriptions fetched per SmartRecruiters/Workday company")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--no-ai-boards", action="store_true",
                   help="do not ask the local model (Ollama) for a board when one cannot be found")
    p.add_argument("--out", help="output JSON path")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("check", help="check every company in the list answers")
    p.add_argument("--companies")
    p.add_argument("--companies-file")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--no-ai-boards", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("resolve", help="find the right job board for every row (--write fixes companies.txt)")
    p.add_argument("--companies")
    p.add_argument("--companies-file")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--write", action="store_true", help="rewrite companies.txt from what answered (keeps a .bak)")
    p.add_argument("--refresh", action="store_true", help="ignore the cache and re-check every company")
    p.add_argument("--no-ai-boards", action="store_true")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("find", help="find which job board a company uses")
    p.add_argument("names", nargs="+", help="company names, or a careers URL")
    p.add_argument("--no-ai-boards", action="store_true")
    p.set_defaults(fn=cmd_find)

    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
