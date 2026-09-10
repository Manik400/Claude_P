"""PC-side publisher: push locally generated pages to the phone site.

    python phone_publish.py naukri                      newest Naukri openings + interview-prep pages
    python phone_publish.py jobhunt <report.html> [--title "..."]   a job-hunt report made on this PC
    python phone_publish.py site                        just refresh the phone UI on gh-pages

Reads %LOCALAPPDATA%\\JobHuntPhone\\config.json (written by setup_phone.bat) for the
passphrase and keeps a small clone of the gh-pages branch next to it. Files already
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
        return json.load(f)


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


def publish(cfg, pages, kind, path, title, replace=False):
    env = dict(os.environ)
    env.setdefault("SITE_PASSPHRASE", cfg.get("passphrase", ""))
    args = PY + [os.path.join(HERE, "publish.py"), "report", "--pages", pages, "--kind", kind,
                 "--title", title, "--file", path]
    if replace:
        args.append("--replace-same-title")
    run(args, env=env)


def push(pages, message):
    run(PY + [os.path.join(HERE, "pages_git.py"), "push", pages, message])


def _stamp(path):
    return "%s:%d" % (os.path.abspath(path).lower(), int(os.path.getmtime(path)))


def cmd_naukri(a):
    cfg = load_config()
    pages = pages_dir(cfg)
    done = cfg.setdefault("published", {})
    count = 0
    openings = sorted(glob.glob(os.path.join(NAUKRI, "data", "jobs", "openings-*.html")), key=os.path.getmtime)
    preps = sorted(glob.glob(os.path.join(NAUKRI, "data", "interview", "interview-prep-*.html")), key=os.path.getmtime)
    for path in openings[-a.max:] + preps[-a.max:]:
        key = _stamp(path)
        if key in done and not a.force:
            continue
        name = os.path.basename(path)
        m = re.search(r"(\d{4}-\d{2}-\d{2})(?:-r(\d+))?", name)
        if name.startswith("openings-"):
            title = "Naukri openings %s%s" % (m.group(1) if m else name, (" run " + m.group(2)) if m and m.group(2) else "")
            publish(cfg, pages, "naukri", path, title, replace=True)
        else:
            title = "Interview prep %s" % (name[len("interview-prep-"):-len(".html")])
            publish(cfg, pages, "interview", path, title, replace=True)
        done[key] = title
        count += 1
    save_config(cfg)
    if count:
        push(pages, "naukri: %d page(s)" % count)
    else:
        print("phone_publish: nothing new to publish")


def cmd_jobhunt(a):
    cfg = load_config()
    pages = pages_dir(cfg)
    title = a.title or os.path.basename(os.path.dirname(os.path.abspath(a.report)))
    publish(cfg, pages, "jobhunt", a.report, title)
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
