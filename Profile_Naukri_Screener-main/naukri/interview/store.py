"""Where interview-prep data lives, and how it is read back.

One file per analysis date, plus two cross-day files:

    data/interview/prep-<date>.json   the whole day's analysis and 100 Q&A
    data/interview/index.json         date -> summary, for the history picker
    data/interview/bank.json          every question ever asked, fingerprinted

The bank is what makes rule 4 hold across days rather than only within a
single run. Without it, day two regenerates the same "explain the Page Object
Model" question day one already produced, and the corpus you are studying
stops growing.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

log = logging.getLogger("naukri.interview.store")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"
PREP_DIR = ROOT / "data" / "interview"
INDEX_PATH = PREP_DIR / "index.json"
BANK_PATH = PREP_DIR / "bank.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("%s unreadable (%s); starting fresh", path.name, exc)
        return default


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return path


# --------------------------------------------------------------- scan results

def results_path(day: str | None = None) -> Path:
    return JOBS_DIR / f"results-{day or date.today().isoformat()}.json"


def load_results(day: str | None = None) -> dict:
    """The scan output for a day. Raises if that day was never scanned."""
    path = results_path(day)
    if not path.exists():
        raise FileNotFoundError(
            f"No scan results for {day or 'today'} ({path.name}).\n"
            f"  Run the scan first:  python main.py --jobs-export --worldwide "
            f"--top 60 --posted-days 1 --new-only")
    return json.loads(path.read_text(encoding="utf-8"))


def available_scan_dates() -> list[str]:
    dates = []
    for path in JOBS_DIR.glob("results-*.json"):
        stem = path.stem.replace("results-", "")
        if len(stem) == 10 and stem.count("-") == 2:
            dates.append(stem)
    return sorted(dates, reverse=True)


# ------------------------------------------------------------------ prep files
#
# Files are keyed on a RUN id, not a date: "2026-08-25-r2" is the second run of
# the 25th. The scan runs three times a day and rewrites results-<date>.json
# each time, so a prep keyed on the date alone would silently overwrite the
# morning's hundred questions with the afternoon's - the page you were studying
# from would change under you at 13:23. A run id keeps each scan's findings as
# its own permanent snapshot, and because it sorts date-first the history
# picker still groups by day.

RUN_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-r(\d+)$")


def run_id(day: str, run: int) -> str:
    return f"{day}-r{run}"


def split_run(stamp: str) -> tuple[str, int]:
    """"2026-08-25-r2" -> ("2026-08-25", 2). Bare dates read as run 1."""
    match = RUN_RE.match(stamp or "")
    if match:
        return match.group(1), int(match.group(2))
    return stamp, 1


def prep_path(stamp: str) -> Path:
    return PREP_DIR / f"prep-{stamp}.json"


def load_prep(stamp: str) -> dict | None:
    """Load one run. A bare date falls back to that day's latest run."""
    direct = _read_json(prep_path(stamp), None)
    if direct is not None:
        return direct
    if not RUN_RE.match(stamp or ""):
        runs = runs_for(stamp)
        if runs:
            return _read_json(prep_path(runs[0]), None)
    return None


def save_prep(prep: dict) -> Path:
    stamp = prep.get("run_id") or prep["date"]
    path = _write_json(prep_path(stamp), prep)
    _update_index(prep)
    return path


def prep_runs() -> list[str]:
    """Every run id on disk, newest first."""
    stamps = []
    for path in PREP_DIR.glob("prep-*.json"):
        stem = path.stem.replace("prep-", "", 1)
        if RUN_RE.match(stem):
            stamps.append(stem)
        elif len(stem) == 10 and stem.count("-") == 2:
            stamps.append(stem)          # a pre-run-id file from an earlier build
    return sorted(stamps, key=_sort_key, reverse=True)


def _sort_key(stamp: str) -> tuple[str, int]:
    day, run = split_run(stamp)
    return day, run


def runs_for(day: str) -> list[str]:
    """That day's run ids, newest first."""
    return [s for s in prep_runs() if split_run(s)[0] == day]


def next_run(day: str) -> int:
    """The run number a fresh analysis of `day` should claim."""
    existing = [split_run(s)[1] for s in runs_for(day)]
    return max(existing) + 1 if existing else 1


def prep_dates() -> list[str]:
    """Distinct dates that have at least one run, newest first."""
    seen = []
    for stamp in prep_runs():
        day = split_run(stamp)[0]
        if day not in seen:
            seen.append(day)
    return seen


def _update_index(prep: dict) -> None:
    index = _read_json(INDEX_PATH, {})
    stamp = prep.get("run_id") or prep["date"]
    day, run = split_run(stamp)
    index[stamp] = {
        "run_id": stamp,
        "date": day,
        "run": run,
        "generated_at": prep.get("generated_at"),
        "scan_at": (prep.get("source") or {}).get("results_mtime"),
        "jobs": len(prep.get("jobs") or []),
        "questions": len(prep.get("questions") or []),
        "top_role": (prep.get("target_profile") or {}).get("primary_role"),
        "top_skills": [s["skill"] for s in (prep.get("skill_matrix") or [])[:6]],
        "top10_job_ids": (prep.get("source") or {}).get("top10_job_ids") or [],
        "page": f"interview-prep-{stamp}.html",
    }
    _write_json(INDEX_PATH, index)


def load_index() -> dict:
    return _read_json(INDEX_PATH, {})


# ------------------------------------------------------------- question bank

def load_bank() -> dict:
    """stable_id -> {question, answer, skill, level, first_seen, dates[]}."""
    bank = _read_json(BANK_PATH, {})
    if not isinstance(bank, dict):
        return {}
    return _compact(bank)


def _merge(into: dict, entry: dict) -> dict:
    """Fold one bank entry into another for the same question."""
    dates = sorted(set((into.get("dates") or []) + (entry.get("dates") or [])))
    firsts = [d for d in (into.get("first_seen"), entry.get("first_seen")) if d]
    return {
        "question": into.get("question") or entry.get("question"),
        # Keep whichever answer has more in it. A later run's replacement is
        # usually the fuller one, but not always, and losing the better answer
        # to re-keying would be a silent downgrade of something already studied.
        "answer": max((into.get("answer") or "", entry.get("answer") or ""), key=len),
        "skill": into.get("skill") or entry.get("skill") or "",
        "level": into.get("level") or entry.get("level") or "",
        "first_seen": min(firsts) if firsts else (dates[0] if dates else None),
        "dates": dates,
    }


def _compact(bank: dict) -> dict:
    """Re-key the bank on stable ids, merging anything that collapses.

    Older files are keyed on the concept fingerprint, which moves whenever the
    synonym map or stopword list is tuned - so the same question ends up stored
    twice under two keys and "have I asked this before?" starts answering no.
    This runs on every load and rewrites the file only when something actually
    changed, so the migration costs nothing on a healthy bank.
    """
    from .dedupe import stable_id

    out: dict[str, dict] = {}
    changed = False
    for key, entry in bank.items():
        question = (entry or {}).get("question")
        if not question:
            changed = True
            continue
        proper = stable_id(question)
        if proper != key:
            changed = True
        out[proper] = _merge(out[proper], entry) if proper in out else dict(entry)

    if changed:
        log.info("Question bank re-keyed: %d entr%s -> %d",
                 len(bank), "y" if len(bank) == 1 else "ies", len(out))
        _write_json(BANK_PATH, out)
    return out


def save_bank(bank: dict) -> Path:
    return _write_json(BANK_PATH, bank)


def remember(bank: dict, questions: list[dict], day: str) -> dict:
    """Fold a day's questions into the bank, recording which days used each."""
    from .dedupe import stable_id

    for item in questions:
        key = stable_id(item["question"])
        fresh = {
            "question": item["question"],
            "answer": item.get("answer", ""),
            "skill": item.get("skill", ""),
            "level": item.get("level", ""),
            "first_seen": day,
            "dates": [day],
        }
        bank[key] = _merge(bank[key], fresh) if key in bank else fresh
    return bank
