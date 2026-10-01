"""GitHub Actions entry point: search company career pages with the phone's inputs and publish the result.

    python run_careers.py search     read this job's part of the company list (SHARD=2/4) into CAREERS_PARTS
    python run_careers.py publish    merge every part in CAREERS_PARTS into one report and publish it
    python run_careers.py            both, for the whole list in one go (local use)

careers.yml runs `search` in parallel jobs, one part of the list each - the whole list (~9k boards)
does not fit in one job's time, and a part that stops early used to mean the end of the list was
never read - then one `publish` job.

Inputs come from the environment (set by .github/workflows/careers.yml):
    INPUT_ROLE        "software engineer, backend engineer"   (comma-separated, required)
    INPUT_EXPERIENCE  "4" or "3-5"                            (optional)
    INPUT_COUNTRIES   "worldwide" or "NL,Germany,TH"          (optional; worldwide when empty)
    INPUT_RELOCATION  strict | visa | any                     (optional)
    INPUT_FIT         default | strict | all                  (optional)
    INPUT_DAYS        "30"                                    (optional; all open postings when empty)
    INPUT_COMPANIES   "agoda, adyen"                          (optional; whole list when empty)
    SHARD             "2/4"                                   (search: which part of the list)
    CAREERS_PARTS     folder the parts are written to / merged from (default $RUNNER_TEMP/parts)
    RESUME_TEXT       resume as plain text (repo secret)      (optional; enables match scoring)
    PAGES_REPO_URL    push URL for the gh-pages branch        (set by the workflow)

The result is JSON (not HTML): the phone page's Careers tab renders it with filters.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BOT = os.path.join(ROOT, "job-hunt", "scripts", "careers_bot.py")


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def roles():
    out = [r.strip() for r in env("INPUT_ROLE").split(",") if r.strip()]
    if not out:
        raise SystemExit("INPUT_ROLE is required")
    return out


def work_dir():
    work = os.path.abspath(env("RUNNER_TEMP", "work"))
    os.makedirs(work, exist_ok=True)
    return work


def parts_dir():
    d = os.path.abspath(env("CAREERS_PARTS") or os.path.join(work_dir(), "parts"))
    os.makedirs(d, exist_ok=True)
    return d


def run_bot(argv):
    """Run careers_bot, echo its output, return the summary line it prints last."""
    print("running:", " ".join(argv[1:]), flush=True)
    r = subprocess.run(argv, text=True, encoding="utf-8", errors="replace", capture_output=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit("careers_bot failed with exit code %d" % r.returncode)
    for line in reversed(r.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return {}


def search():
    work = work_dir()
    shard = env("SHARD")
    out = os.path.join(parts_dir(), "careers-%s.json" % (shard.replace("/", "-of-") if shard else "all"))
    argv = [sys.executable, BOT, "run", "--out", out, "--role", ",".join(roles()),
            "--countries", env("INPUT_COUNTRIES", "worldwide"), "--relocation", env("INPUT_RELOCATION", "any"),
            "--fit", env("INPUT_FIT", "default"), "--days", env("INPUT_DAYS") or "0",
            # ~10k boards on many hosts; each host is still throttled on its own
            "--workers", env("INPUT_WORKERS", "32"),
            # The job is killed at 90 min (careers.yml) and a killed run publishes nothing. A part
            # of the list takes ~10 min; this is only the safety net if a board host crawls.
            "--max-minutes", env("INPUT_MAX_MINUTES", "65")]
    if shard:
        argv += ["--shard", shard]
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
    summary = run_bot(argv)
    if not os.path.exists(out):
        raise SystemExit("careers_bot wrote no result")
    print("part %s: %s jobs from %s companies" % (shard or "all", summary.get("jobs", "?"), summary.get("companies", "?")))


def publish():
    work = work_dir()
    found = sorted(glob.glob(os.path.join(parts_dir(), "careers-*.json")))
    if not found:
        raise SystemExit("no search part finished - nothing to publish")
    out = os.path.join(work, "careers.json")
    summary = run_bot([sys.executable, BOT, "merge", out] + found)

    title = ", ".join(roles())
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
    print("done: %s jobs (%s with relocation) from %s companies published for %s"
          % (summary.get("jobs", "?"), summary.get("relocation", "?"), summary.get("companies", "?"), title))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "search":
        search()
    elif mode == "publish":
        publish()
    elif not mode:
        os.environ["CAREERS_PARTS"] = tempfile.mkdtemp(prefix="careers-parts-")   # no parts of older runs
        search()
        publish()
    else:
        raise SystemExit("usage: run_careers.py [search|publish]")


if __name__ == "__main__":
    main()
