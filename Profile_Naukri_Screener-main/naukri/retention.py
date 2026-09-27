"""Delete generated reports older than 30 days.

Only dated report output goes: the openings pages, scan results and exports,
interview-prep runs, company-site screenshots, tailored resumes and the
worldwide job-hunt run folders in Documents\\JobHunt. The records the agent
works from - the ledger, applications.jsonl, the answer bank, questions.yaml,
jobs.yaml, the interview question bank - are never touched.

The phone site prunes its own copies on the same schedule (site/tools/publish.py).
Runs at the start of every scan and interview prep (main.py).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger("naukri.retention")

RETENTION_DAYS = 30
ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "data" / "jobs"
INTERVIEW = ROOT / "data" / "interview"
JOBHUNT = Path.home() / "Documents" / "JobHunt"

# (folder, pattern) - the day is read from the file name
DATED = [
    (JOBS, "openings-*.html"), (JOBS, "results-*.json"), (JOBS, "job-matches-*.xlsx"),
    (JOBS, "runs-*.json"), (JOBS, "report-*.md"),
    (INTERVIEW, "interview-prep-*.html"), (INTERVIEW, "prep-*.json"),
    (INTERVIEW, "analysis-*.json"), (INTERVIEW, "partial-*.json"),
]
# (folder, pattern) - named 20260926-1448-..., the day is the leading yyyymmdd
STAMPED = [(JOBS / "career_shots", "*.png"), (JOBS / "tailored", "*.docx")]
DAY = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")
RUN_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}_")      # Documents\JobHunt\2026-09-26_1048_software-engineer


def _day(name: str) -> dt.date | None:
    m = DAY.search(name)
    if not m:
        return None
    try:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def expired(days: int = RETENTION_DAYS, today: dt.date | None = None,
            jobhunt: Path | None = JOBHUNT) -> list[Path]:
    """Every report file / run folder older than `days` days."""
    cutoff = (today or dt.date.today()) - dt.timedelta(days=days)
    out: list[Path] = []
    for folder, pattern in DATED + STAMPED:
        if folder.is_dir():
            out += [p for p in folder.glob(pattern) if p.is_file() and (_day(p.name) or cutoff) < cutoff]
    if jobhunt and jobhunt.is_dir():
        out += [p for p in jobhunt.iterdir() if p.is_dir() and RUN_DIR.match(p.name) and (_day(p.name) or cutoff) < cutoff]
    return out


def prune(days: int = RETENTION_DAYS, today: dt.date | None = None, jobhunt: Path | None = JOBHUNT) -> int:
    """Delete what `expired` lists; returns how many went. Never raises."""
    gone = 0
    for path in expired(days, today, jobhunt):
        try:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
            gone += 1
        except OSError as exc:
            log.warning("could not delete %s: %s", path, exc)
    _prune_interview_index(days, today)
    if gone:
        log.info("Deleted %d report(s) older than %d days", gone, days)
    return gone


def _prune_interview_index(days: int, today: dt.date | None) -> None:
    """Drop the history picker's entries for interview runs whose files are gone."""
    path = INTERVIEW / "index.json"
    if not path.exists():
        return
    cutoff = (today or dt.date.today()) - dt.timedelta(days=days)
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    keep = {k: v for k, v in index.items() if (_day(k) or cutoff) >= cutoff}
    if len(keep) != len(index):
        path.write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
