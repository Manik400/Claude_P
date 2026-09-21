"""GitHub Actions entry point: run the job-hunt bot with the phone's inputs and publish the report.

Inputs come from the environment (set by .github/workflows/jobhunt.yml):
    INPUT_ROLE        "python developer, backend engineer"   (comma-separated, required)
    INPUT_EXPERIENCE  "3" or "2-4"                            (optional)
    INPUT_COUNTRIES   "DE,NL,India"                           (optional; bot default when empty)
    INPUT_DAYS        "14"                                    (optional)
    INPUT_HOURS       "2" or "0.5"                            (optional; wins over INPUT_DAYS)
    INPUT_ALLOW_UNDATED "true"                                (optional; with INPUT_HOURS, keep postings
                                                               whose exact time the board never stated)
    INPUT_PLATFORMS   "linkedin,seek,The Muse"                (optional; empty = every platform set up)
    INPUT_FIT         default | strict | all                  (optional)
    INPUT_EXTRA       any extra job_bot flags                 (optional)
    RESUME_TEXT       resume as plain text (repo secret)      (optional; enables match scoring)
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
    if env("INPUT_HOURS"):
        argv += ["--hours", env("INPUT_HOURS")]
    if env("INPUT_ALLOW_UNDATED").lower() in ("1", "true", "yes", "on"):
        argv += ["--allow-undated"]
    if env("INPUT_PLATFORMS"):
        argv += ["--sources", env("INPUT_PLATFORMS")]
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
    r = subprocess.run(argv, text=True, encoding="utf-8", errors="replace", capture_output=True)
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
    # the run's own meta (job_bot writes run.json) knows the window it really used and the
    # platform keys it was asked for; fall back to the inputs when it is missing.
    run_meta = {}
    try:
        with open(os.path.join(run_dir, "run.json"), encoding="utf-8") as f:
            run_meta = (json.load(f) or {}).get("meta") or {}
    except (OSError, ValueError):
        pass

    def meta_num(key):
        v = run_meta.get(key)
        if v is None or v == "" or isinstance(v, bool):
            return ""
        return "%g" % v if isinstance(v, (int, float)) else str(v)

    def meta_list(key, fallback=""):
        v = run_meta.get(key)
        return ",".join(str(x) for x in v) if isinstance(v, (list, tuple)) else fallback

    pages = os.path.join(work, "pages")
    py = [sys.executable]
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "checkout", pages], check=True)
    subprocess.run(py + [os.path.join(HERE, "publish.py"), "site", "--pages", pages], check=True)
    attach = []
    if os.path.exists(os.path.join(run_dir, "jobs.json")):
        attach = ["--attach", os.path.join(run_dir, "jobs.json")]
    subprocess.run(py + [os.path.join(HERE, "publish.py"), "report", "--pages", pages, "--kind", "jobhunt",
                         "--title", title, "--file", report] + attach + [
                         "--meta", "jobs=%s" % summary.get("jobs", ""),
                         "--meta", "countries=%s" % countries,
                         "--meta", "experience=%s" % env("INPUT_EXPERIENCE"),
                         "--meta", "days=%s" % (meta_num("days") or env("INPUT_DAYS")),
                         "--meta", "hours=%s" % (meta_num("hours") or env("INPUT_HOURS")),
                         "--meta", "window_hours=%s" % meta_num("window_hours"),
                         "--meta", "platforms_asked=%s" % meta_list("platforms_asked", env("INPUT_PLATFORMS")),
                         "--meta", "platforms=%s" % meta_list("platforms")], check=True)
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "push", pages,
                         "job-hunt report: %s (%s)" % (title, countries)], check=True)
    print("done: %s jobs published for %s" % (summary.get("jobs", "?"), title))


if __name__ == "__main__":
    main()
