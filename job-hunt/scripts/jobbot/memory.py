"""What you are done with, and what you were already shown - so no report repeats a job.

Two memories, asked after every search and every merge:

  * done     the Naukri screener's tracker (naukri/jobs/tracker.py): every job applied to on
             any board, every job removed on the phone, every row in your Google Sheet. A
             posting that matches by id, link, or same title at the same company is dropped
             from the run - never listed, never applied to again.
  * seen     ~/Documents/JobHunt/seen.json: the link (and title+company) of every posting a
             report has already listed, with the run that first showed it. A later run drops
             it from ITS report: you read each posting once. Applying is not affected - the
             apply pass carries unapplied postings from earlier runs itself (job_bot.backlog_jobs).

Entries older than SEEN_DAYS fall out, so a posting re-opened months later is news again.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

from jobbot.autoapply import linkedin_id, sibling_dir
from jobbot.config import DEFAULT_OUT_ROOT

SEEN_PATH = os.path.join(DEFAULT_OUT_ROOT, "seen.json")
SEEN_DAYS = 60


def tracker():
    """The sibling project's tracker module, or None when it is not next door."""
    root = sibling_dir()
    if not root:
        return None
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from naukri.jobs import tracker as mod  # noqa: E402
        return mod
    except ImportError:
        return None


def is_done(job, mem=None) -> str | None:
    """Why this posting is done with (applied / removed), or None."""
    mod = tracker()
    if mod is None:
        return None
    mem = mem or mod.Memory.shared()
    lid = linkedin_id(getattr(job, "url", "") or "")
    return mem.blocked(key=f"linkedin:{lid}" if lid else None, url=getattr(job, "url", ""),
                       company=getattr(job, "company", ""), title=getattr(job, "title", ""))


def drop_done(jobs, log=None) -> list:
    mod = tracker()
    if mod is None:
        return list(jobs)
    mem = mod.Memory.shared()
    kept, dropped = [], 0
    for j in jobs:
        if is_done(j, mem):
            dropped += 1
        else:
            kept.append(j)
    if dropped and log:
        log(f"tracker: {dropped} posting(s) left out - already applied to, or removed by you (any board, the sheet, the phone)")
    return kept


def _load_seen() -> dict:
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_seen(seen: dict) -> None:
    cutoff = time.time() - SEEN_DAYS * 86400
    seen = {k: v for k, v in seen.items() if isinstance(v, dict) and v.get("ts", 0) >= cutoff}
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    tmp = SEEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)
    os.replace(tmp, SEEN_PATH)


def drop_seen(jobs, run_id: str, log=None) -> list:
    """Keep what this run shows for the first time; a posting an earlier run already
    listed is left out. Postings first seen by THIS run stay (a merge into the same
    run is not a repeat)."""
    seen = _load_seen()
    now = time.time()
    stamp = datetime.now().isoformat(timespec="seconds")
    kept, repeats = [], 0
    for j in jobs:
        ids = [j.dedup_url(), "k:" + "|".join(j.dedup_key())]
        earlier = [seen[i] for i in ids if i in seen and seen[i].get("run") != run_id]
        if earlier:
            repeats += 1
            continue
        for i in ids:
            seen.setdefault(i, {"run": run_id, "at": stamp, "ts": now, "title": j.title, "company": j.company})
        kept.append(j)
    _save_seen(seen)
    if repeats and log:
        log(f"seen before: {repeats} posting(s) an earlier report already listed are left out of this one")
    return kept


def fresh_only(jobs, run_id: str, log=None) -> list:
    """drop_done, then drop_seen - what every report goes through."""
    return drop_seen(drop_done(jobs, log), run_id, log)
