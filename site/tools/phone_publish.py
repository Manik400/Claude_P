"""PC-side publisher: push locally generated pages to the phone site.

    python phone_publish.py naukri                      newest Naukri openings + interview-prep pages + applications log
    python phone_publish.py jobhunt <report.html> [--title "..."]   a job-hunt report made on this PC
    python phone_publish.py site                        just refresh the phone UI on gh-pages

Reads %LOCALAPPDATA%\\JobHuntPhone\\config.json (written by setup_phone.bat) for the
repo and keeps a small clone of the gh-pages branch next to it. Files already
published (same path + modification time) are skipped, so this is safe to run after
every scan or from Task Scheduler.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NAUKRI = os.path.join(ROOT, "Profile_Naukri_Screener-main")
PY = [sys.executable]


def config_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JobHuntPhone")


def load_config():
    p = os.path.join(config_dir(), "config.json")
    if not os.path.exists(p):
        raise SystemExit("phone_publish: run site\\setup_phone.bat first (no %s)" % p)
    with open(p, encoding="utf-8") as f:
        cfg = json.load(f)
    # Optional API keys for the PC side (contacts providers, Apify), kept out of the repo:
    #   "env": {"HUNTER_API_KEY": "...", "SIGNALHIRE_API_KEY": "..."}
    for k, v in (cfg.get("env") or {}).items():
        os.environ.setdefault(k, str(v))
    return cfg


def save_config(cfg):
    os.makedirs(config_dir(), exist_ok=True)
    with open(os.path.join(config_dir(), "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)


def run(args, **kw):
    subprocess.run(args, check=True, **kw)


def pages_dir(cfg):
    d = os.path.join(config_dir(), "pages")
    env = dict(os.environ)
    if cfg.get("repo_url"):
        env["PAGES_REPO_URL"] = cfg["repo_url"]
    run(PY + [os.path.join(HERE, "pages_git.py"), "checkout", d], env=env)
    run(PY + [os.path.join(HERE, "publish.py"), "site", "--pages", d])
    return d


def publish(cfg, pages, kind, path, title, replace=False, attach=None):
    env = dict(os.environ)
    args = PY + [os.path.join(HERE, "publish.py"), "report", "--pages", pages, "--kind", kind,
                 "--title", title, "--file", path]
    if replace:
        args.append("--replace-same-title")
    if attach and os.path.exists(attach):
        args += ["--attach", attach]
    run(args, env=env)


def push(pages, message):
    run(PY + [os.path.join(HERE, "pages_git.py"), "push", pages, message])


def _stamp(path):
    return "%s:%d" % (os.path.abspath(path).lower(), int(os.path.getmtime(path)))


def naukri_jobs_file(day):
    """The scan's results-<day>.json as the common job-list format the phone
    and the queue understand (same shape as job-hunt's jobs.json)."""
    src = os.path.join(NAUKRI, "data", "jobs", "results-%s.json" % day)
    if not os.path.exists(src):
        return None
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    jobs = []
    for j in data.get("naukri") or []:
        jobs.append({
            "source": "naukri", "source_name": "Naukri", "title": j.get("title") or "", "company": j.get("company") or "",
            "url": j.get("url") or "", "country": "IN", "location": j.get("location") or "", "posted": None,
            "salary": j.get("salary_label") or "", "snippet": (j.get("description") or "")[:300],
            "skills": j.get("skills") or [], "exp_min": j.get("min_exp"), "exp_max": j.get("max_exp"),
            "fit": "unknown", "score": j.get("score"), "matched_skills": j.get("matched_skills") or [],
            "id": "nk%s" % j.get("job_id"),
            "extra": {"naukri_id": str(j.get("job_id") or ""), "company_apply": bool(j.get("company_apply")),
                      "has_questionnaire": bool(j.get("has_questionnaire")), "apply_status": j.get("apply_status") or "",
                      "experience": j.get("experience_label") or "", "rating": j.get("company_rating")},
        })
    for c in data.get("linkedin") or []:
        loc = c.get("location") or ""
        jobs.append({
            "source": "linkedin", "source_name": "LinkedIn", "title": c.get("title") or "", "company": c.get("company") or "",
            "url": c.get("url") or "", "country": "IN" if "india" in loc.lower() else ("REMOTE" if c.get("_remote") else "??"),
            "location": loc, "posted": None, "salary": "", "snippet": " · ".join(c.get("metadata") or [])[:300],
            "skills": [], "fit": "unknown", "score": c.get("_match"), "id": "li%s" % c.get("job_id"),
            "extra": {"linkedin_id": str(c.get("job_id") or ""), "easy_apply": bool(c.get("easy_apply")),
                      "apply_status": c.get("apply_status") or ""},
        })
    # Recruiter / hiring-manager contacts per company, when any provider key is set
    # (SIGNALHIRE_API_KEY / HUNTER_API_KEY / APOLLO_API_KEY in the environment or config.json "env").
    try:
        sys.path.insert(0, os.path.join(ROOT, "job-hunt", "scripts"))
        from jobbot import contacts
        from jobbot.http import Http
        if contacts.providers():
            contacts.attach(jobs, contacts.enrich(jobs, Http(), ["software engineer"], log=print, max_companies=20))
    except Exception as exc:  # noqa: BLE001 - a bonus, never a reason not to publish
        print("phone_publish: contacts skipped (%s)" % exc)
    out = os.path.join(config_dir(), "naukri-jobs-%s.json" % day)
    os.makedirs(config_dir(), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False)
    return out


def published_titles(pages):
    """(kind, title) of everything the live gh-pages index still carries.

    The local "published" stamps say what this PC once pushed; they are not
    evidence the page is still on the branch. A pruned report, a recreated
    branch or a migration that dropped items all leave the stamp behind, and
    then every later run reports "nothing new to publish" while the phone shows
    no Naukri scans at all. Checking the branch instead makes a missing page
    come back by itself on the next run.
    """
    p = os.path.join(pages, "data", "index.json")
    if not os.path.exists(p):
        return set()
    try:
        with open(p, encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return set()
    return {(i.get("kind"), i.get("title")) for i in idx.get("items") or []}


def hidden_titles(pages):
    """(kind, title) of reports removed from the phone (phone_apply.remove_reports): never republished."""
    try:
        with open(os.path.join(pages, "data", "index.json"), encoding="utf-8") as f:
            return {tuple(h) for h in json.load(f).get("hidden") or [] if len(h) == 2}
    except (OSError, ValueError, TypeError):
        return set()


def _scan_kind(path):
    """" - Early" etc. from the page's <title>, written by naukri/jobs/page.py."""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4096)
    except OSError:
        return ""
    m = re.search(r"<title>[^<]*?( - [^<]+)</title>", head)
    return m.group(1) if m else ""


def page_title(path):
    """The (kind, title) one locally generated page is published under."""
    name = os.path.basename(path)
    m = re.search(r"(\d{4}-\d{2}-\d{2})(?:-r(\d+))?", name)
    if name == "applications.html":
        return "applications", "Applications sent"
    if name == "accuracy.html":
        return "accuracy", "Accuracy & learning"
    if name.startswith("openings-"):
        day = m.group(1) if m else ""
        title = "Naukri openings %s%s" % (day or name, (" run " + m.group(2)) if m and m.group(2) else "")
        return "naukri", title + _scan_kind(path)
    return "interview", "Interview prep %s" % (name[len("interview-prep-"):-len(".html")])


def cmd_naukri(a):
    cfg = load_config()
    pages = pages_dir(cfg)
    done = cfg.setdefault("published", {})
    live = published_titles(pages)
    hidden = hidden_titles(pages)
    count = 0
    openings = sorted(glob.glob(os.path.join(NAUKRI, "data", "jobs", "openings-*.html")), key=os.path.getmtime)
    preps = sorted(glob.glob(os.path.join(NAUKRI, "data", "interview", "interview-prep-*.html")), key=os.path.getmtime)
    # The openings page links to applications.html (the "Applications sent"
    # tab) and to the interview pages by relative file name; the phone page
    # resolves those clicks against the published copies, so the log page
    # travels with the scans. One copy is kept, replaced whenever it changes.
    applications = os.path.join(NAUKRI, "data", "jobs", "applications.html")
    # The daily accuracy / self-learning page (naukri/learning.py), one copy.
    accuracy = os.path.join(NAUKRI, "data", "metrics", "accuracy.html")
    extra = [p for p in (applications, accuracy) if os.path.exists(p)]
    for path in openings[-a.max:] + preps[-a.max:] + extra:
        key = _stamp(path)
        kind, title = page_title(path)
        if key in done and (kind, title) in live and not a.force:
            continue
        if (kind, title) in hidden and kind in ("naukri", "interview"):
            continue            # you removed it on the phone
        name = os.path.basename(path)
        if kind == "naukri":
            m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
            day = m.group(1) if m else ""
            publish(cfg, pages, "naukri", path, title, replace=True,
                    attach=naukri_jobs_file(day) if day else None)
        else:
            publish(cfg, pages, kind, path, title, replace=True)
        done[key] = title
        live.add((kind, title))
        count += 1
    save_config(cfg)
    if count and not a.no_push:
        push(pages, "naukri: %d page(s)" % count)
    elif count:
        print("phone_publish: %d page(s) staged; the queue run pushes them" % count)
    else:
        print("phone_publish: nothing new to publish")


def cmd_jobhunt(a):
    cfg = load_config()
    pages = pages_dir(cfg)
    title = a.title or os.path.basename(os.path.dirname(os.path.abspath(a.report)))
    jobs_json = os.path.join(os.path.dirname(os.path.abspath(a.report)), "jobs.json")
    publish(cfg, pages, "jobhunt", a.report, title, attach=jobs_json)
    push(pages, "job-hunt report (PC): %s" % title)


def cmd_site(a):
    cfg = load_config()
    pages = pages_dir(cfg)
    push(pages, "phone site: update UI")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    n = sub.add_parser("naukri")
    n.add_argument("--max", type=int, default=3, help="newest N pages of each type to consider")
    n.add_argument("--force", action="store_true", help="re-publish even if already published")
    n.add_argument("--no-push", action="store_true", dest="no_push", help="stage in the clone; the caller pushes")
    n.set_defaults(fn=cmd_naukri)
    j = sub.add_parser("jobhunt")
    j.add_argument("report")
    j.add_argument("--title")
    j.set_defaults(fn=cmd_jobhunt)
    s = sub.add_parser("site")
    s.set_defaults(fn=cmd_site)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
