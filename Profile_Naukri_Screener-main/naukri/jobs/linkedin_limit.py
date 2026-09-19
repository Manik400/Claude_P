"""LinkedIn's daily Easy Apply limit, remembered for 24 hours.

When LinkedIn answers an Easy Apply click with "you've reached the limit",
every further Easy Apply that day is a wasted page load - and a run every
30 minutes makes a lot of them. So the moment is written to
data/jobs/linkedin_limit.json and, until COOLDOWN_HOURS later, Easy Apply
postings are left alone: not clicked, not recorded, not counted as attempts.
Everything else carries on - Naukri, the other boards, company career sites,
and LinkedIn postings whose Apply leads off LinkedIn (those never touched the
limit).

    active()   True while the pause holds
    label()    "Easy Apply paused until 2026-09-21 03:41" for logs and the phone
    hit()      LinkedIn just said the limit is reached: start the pause
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "data" / "jobs" / "linkedin_limit.json"
COOLDOWN_HOURS = 24


def until() -> datetime | None:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def active() -> bool:
    end = until()
    return bool(end and datetime.now() < end)


def label() -> str:
    end = until()
    if not end or datetime.now() >= end:
        return ""
    return f"Easy Apply paused until {end.strftime('%Y-%m-%d %H:%M')} (LinkedIn's daily limit)"


def hit(hours: float = COOLDOWN_HOURS) -> datetime:
    """Record that the limit was reached now. Returns when the pause ends."""
    end = datetime.now() + timedelta(hours=hours)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"hit_at": datetime.now().isoformat(timespec="seconds"),
                                "until": end.isoformat(timespec="seconds")}, indent=1),
                    encoding="utf-8")
    return end


def clear() -> None:
    try:
        PATH.unlink()
    except OSError:
        pass
