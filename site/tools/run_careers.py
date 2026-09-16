"""GitHub Actions entry point: search company career pages with the phone's inputs and publish the result.

Inputs come from the environment (set by .github/workflows/careers.yml):
    INPUT_ROLE        "software engineer, backend engineer"   (comma-separated, required)
    INPUT_EXPERIENCE  "4" or "3-5"                            (optional)
    INPUT_COUNTRIES   "worldwide" or "NL,Germany,TH"          (optional; worldwide when empty)
    INPUT_RELOCATION  strict | visa | any                     (optional)
    INPUT_FIT         default | strict | all                  (optional)
    INPUT_DAYS        "30"                                    (optional; all open postings when empty)
    INPUT_COMPANIES   "agoda, adyen"                          (optional; whole list when empty)
    RESUME_TEXT       resume as plain text (repo secret)      (optional; enables match scoring)
    SITE_PASSPHRASE   encrypts the published result           (repo secret, required)
    PAGES_REPO_URL    push URL for the gh-pages branch        (set by the workflow)

The result is JSON (not HTML): the phone page's Careers tab decrypts it and renders it with filters.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BOT = os.path.join(ROOT, "job-hunt", "scripts", "careers_bot.py")


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def main():
    roles = [r.strip() for r in env("INPUT_ROLE").split(",") if r.strip()]
    if not roles:
        raise SystemExit("INPUT_ROLE is required")
    work = os.path.abspath(env("RUNNER_TEMP", "work"))
    os.makedirs(work, exist_ok=True)
    out = os.path.join(work, "careers.json")

    argv = [sys.executable, BOT, "run", "--out", out, "--role", ",".join(roles),
            "--countries", env("INPUT_COUNTRIES", "worldwide"), "--relocation", env("INPUT_RELOCATION", "any"),
            "--fit", env("INPUT_FIT", "default"), "--days", env("INPUT_DAYS") or "0"]
    if env("INPUT_EXPERIENCE"):
        argv += ["--experience", env("INPUT_EXPERIENCE")]
    if env("INPUT_COMPANIES"):
        argv += ["--companies", env("INPUT_COMPANIES")]
    resume_text = os.environ.get("RESUME_TEXT", "")
    if resume_text.strip():
        resume_path = os.path.join(work, "resume.txt")
        with open(resume_path, "w", encoding="utf-8") as f:
            f.write(resume_text)
        argv += ["--resume", resume_path]
        print("resume: using RESUME_TEXT secret (%d chars)" % len(resume_text))
    else:
        print("resume: no RESUME_TEXT secret, jobs will not be scored")

    print("running:", " ".join(argv[1:]), flush=True)
    r = subprocess.run(argv, text=True, encoding="utf-8", errors="replace", capture_output=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0 or not os.path.exists(out):
        raise SystemExit("careers_bot failed with exit code %d" % r.returncode)
    summary = {}
    for line in reversed(r.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                summary = json.loads(line)
                break
            except ValueError:
                pass

    title = ", ".join(roles)
    countries = env("INPUT_COUNTRIES") or "worldwide"
    pages = os.path.join(work, "pages")
    py = [sys.executable]
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "checkout", pages], check=True)
    subprocess.run(py + [os.path.join(HERE, "publish.py"), "site", "--pages", pages], check=True)
    subprocess.run(py + [os.path.join(HERE, "publish.py"), "report", "--pages", pages, "--kind", "careers",
                         "--title", title, "--file", out,
                         "--meta", "jobs=%s" % summary.get("jobs", ""),
                         "--meta", "relocation=%s" % summary.get("relocation", ""),
                         "--meta", "countries=%s" % countries,
                         "--meta", "experience=%s" % env("INPUT_EXPERIENCE"),
                         "--meta", "reloc_mode=%s" % env("INPUT_RELOCATION", "any")], check=True)
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "push", pages,
                         "careers search: %s (%s)" % (title, countries)], check=True)
    print("done: %s jobs (%s with relocation) published for %s" % (summary.get("jobs", "?"), summary.get("relocation", "?"), title))


if __name__ == "__main__":
    main()
