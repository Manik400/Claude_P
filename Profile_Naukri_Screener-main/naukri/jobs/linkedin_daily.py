"""Scheduled runs touch LinkedIn at most once a day: one search, one apply pass.

Every scheduled task (Naukri scans, scan3, the job-hunt rounds every 30 min,
the phone queue) goes through scripts/run_hidden.vbs, which sets
JOBS_SCHEDULED=1. For those runs the first LinkedIn search of the day and the
first LinkedIn apply pass of the day go ahead; every later scheduled run that
day skips LinkedIn and carries on with Naukri, the other boards and company
sites. A run you start yourself (no JOBS_SCHEDULED) is never held back, but
it does use up the day's turn: search LinkedIn by hand in the morning and no
scheduled run searches it again that day.

The day's turns are written to data/jobs/linkedin_daily.json, shared by this
project, job-hunt and the phone queue, so the limit holds across all of them.
A turn is taken when the LinkedIn pass STARTS, so a pass that crashes half-way
is not retried on the next schedule - no more than one try a day.

    scheduled()     True for a run started by Task Scheduler
    allowed(kind)   may this run do LinkedIn `kind` ("search" / "apply")?
    take(kind)      allowed(), and use up today's turn
    label(kind)     "LinkedIn search already ran today at 10:02 (scheduled runs: once a day)"
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "data" / "jobs" / "linkedin_daily.json"
ENV = "JOBS_SCHEDULED"
KINDS = ("search", "apply")


def scheduled() -> bool:
    return os.environ.get(ENV, "").strip() == "1"


def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def last(kind: str) -> datetime | None:
    try:
        return datetime.fromisoformat(_load()[kind])
    except (KeyError, TypeError, ValueError):
        return None


def done_today(kind: str) -> bool:
    at = last(kind)
    return bool(at and at.date() == datetime.now().date())


def allowed(kind: str) -> bool:
    return not scheduled() or not done_today(kind)


def take(kind: str) -> bool:
    """True when this run may do LinkedIn `kind`; either way the day's turn is used up."""
    if kind not in KINDS:
        raise ValueError(kind)
    if scheduled() and done_today(kind):
        return False
    data = _load()
    data[kind] = datetime.now().isoformat(timespec="seconds")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return True


def label(kind: str) -> str:
    at = last(kind)
    if not at or at.date() != datetime.now().date():
        return ""
    return f"LinkedIn {kind} already ran today at {at.strftime('%H:%M')} (scheduled runs: once a day)"
