"""GitHub Actions entry point: run the job-hunt bot with the phone's inputs and publish the report.

Inputs come from the environment (set by .github/workflows/jobhunt.yml):
    INPUT_ROLE        "python developer, backend engineer"   (comma-separated, required)
    INPUT_EXPERIENCE  "3" or "2-4"                            (optional)
    INPUT_COUNTRIES   "DE,NL,India"                           (optional; bot default when empty)
    INPUT_DAYS        "14"                                    (optional)
    INPUT_FIT         default | strict | all                  (optional)
    INPUT_EXTRA       any extra job_bot flags                 (optional)
    RESUME_TEXT       resume as plain text (repo secret)      (optional; enables match scoring)
    SITE_PASSPHRASE   encrypts the published report           (repo secret, required)
    PAGES_REPO_URL    push URL for the gh-pages branch        (set by the workflow)
"""
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
JOB_BOT = os.path.join(ROOT, "job-hunt", "scripts", "job_bot.py")


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def main():
    roles = [r.strip() for r in env("INPUT_ROLE").split(",") if r.strip()]
    if not roles:
        raise SystemExit("INPUT_ROLE is required")
    work = os.path.abspath(env("RUNNER_TEMP", "work"))
    run_dir = os.path.join(work, "jobhunt-run")
    os.makedirs(run_dir, exist_ok=True)

    argv = [sys.executable, JOB_BOT, "run", "--out", run_dir, "--quiet"]
    for r in roles:
        argv += ["--role", r]
    if env("INPUT_EXPERIENCE"):
        argv += ["--experience", env("INPUT_EXPERIENCE")]
    if env("INPUT_COUNTRIES"):
        argv += ["--countries", env("INPUT_COUNTRIES")]
    if env("INPUT_DAYS"):
        argv += ["--days", env("INPUT_DAYS")]
    if env("INPUT_FIT"):
        argv += ["--fit", env("INPUT_FIT")]
    if env("INPUT_EXTRA"):
        argv += shlex.split(env("INPUT_EXTRA"))
    resume_text = os.environ.get("RESUME_TEXT", "")
    if resume_text.strip():
        resume_path = os.path.join(work, "resume.txt")
        with open(resume_path, "w", encoding="utf-8") as f:
            f.write(resume_text)
        argv += ["--resume", resume_path]
        print("resume: using RESUME_TEXT secret (%d chars)" % len(resume_text))
    else:
        print("resume: no RESUME_TEXT secret, jobs will not be scored")

    print("running:", " ".join(shlex.quote(a) for a in argv[1:]), flush=True)
    r = subprocess.run(argv, text=True, capture_output=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit("job_bot failed with exit code %d" % r.returncode)
    summary = {}
    for line in reversed(r.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                summary = json.loads(line)
                break
            except ValueError:
                pass
    report = summary.get("report") or os.path.join(run_dir, "report.html")
    if not os.path.exists(report):
        raise SystemExit("report.html was not produced")

    title = ", ".join(roles)
    countries = env("INPUT_COUNTRIES") or "default countries"
    pages = os.path.join(work, "pages")
    py = [sys.executable]
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "checkout", pages], check=True)
    subprocess.run(py + [os.path.join(HERE, "publish.py"), "site", "--pages", pages], check=True)
    subprocess.run(py + [os.path.join(HERE, "publish.py"), "report", "--pages", pages, "--kind", "jobhunt",
                         "--title", title, "--file", report,
                         "--meta", "jobs=%s" % summary.get("jobs", ""),
                         "--meta", "countries=%s" % countries,
                         "--meta", "experience=%s" % env("INPUT_EXPERIENCE"),
                         "--meta", "days=%s" % env("INPUT_DAYS")], check=True)
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "push", pages,
                         "job-hunt report: %s (%s)" % (title, countries)], check=True)
    print("done: %s jobs published for %s" % (summary.get("jobs", "?"), title))


if __name__ == "__main__":
    main()
