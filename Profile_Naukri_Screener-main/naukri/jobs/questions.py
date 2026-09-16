"""Screening questions the agent could not answer, saved for you to answer once.

The applier answers a recruiter's question only from facts on record (see
answers.py). When it meets one it cannot ground - "what is your expected
CTC", "how many years of NestJS" - it used to abandon the job and leave a
line in a report. Now it writes the question here instead, and you answer it
at the end of the day. Two files, both under data/jobs/:

    questions.yaml     what is waiting for you. One entry per distinct
                       question, listing every job that asked it. Fill in
                       `answer:` and save.
    answer_bank.yaml   every answer you have given. Read on every run, so a
                       question answered once is answered for every later job
                       that asks it, on either board.

Two ways to answer:

    python main.py --answer-questions    walks you through them in the terminal
    edit data/jobs/questions.yaml        type after `answer:` and save

The next scan (or `--jobs-export --apply-found --yes`) absorbs the answers into the bank
and re-attempts the jobs that were waiting on them. `answer: skip` means
"never answer this" - the jobs that asked it stay unapplied, and the question
is not asked again.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

import yaml

log = logging.getLogger("naukri.jobs.questions")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"
PENDING_PATH = JOBS_DIR / "questions.yaml"
BANK_PATH = JOBS_DIR / "answer_bank.yaml"

SKIP = "skip"

PENDING_HEADER = """\
# Questions the job agent could not answer from your profile.
#
# Type your answer after `answer:` and save this file. The next run applies to
# the jobs listed under each question and remembers the answer for every
# future job that asks it (data/jobs/answer_bank.yaml).
#
#   - for a question with `options:`, type one of the options exactly
#   - for a "how many years" question, type a number
#   - leave `answer: ""` to keep it waiting
#   - `answer: skip` means never answer this one; those jobs stay unapplied
#
# Or run:  python main.py --answer-questions
#
"""

BANK_HEADER = """\
# Your answers to screening questions, one per distinct question. Read on
# every run: a question answered once is answered for every later job that
# asks it, on Naukri and on LinkedIn. Edit an answer here to change what is
# sent from now on; delete an entry to be asked again.
#
"""


def key(question: str) -> str:
    """Normalise a question so the same one asked twice matches itself.

    Strips the required-field star, "(required)", case, punctuation and
    whitespace. Skill names keep their "+", "#" and "." so "C#" and "Node.js"
    stay distinct from "C" and "Node".
    """
    text = (question or "").lower()
    text = re.sub(r"\(required\)|\*", " ", text)
    text = re.sub(r"[^a-z0-9+#. ]+", " ", text)
    text = re.sub(r"\s+\.\s+", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .")


def _read_list(path: Path) -> list[dict]:
    """A YAML list from disk, or [] if the file is missing.

    A file that is not valid YAML is moved aside and logged loudly rather
    than silently replaced: a half-edited questions.yaml is your work, and
    the run must not overwrite it with an empty list.
    """
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        broken = path.with_suffix(".broken.yaml")
        log.error("%s is not valid YAML (%s) - moved to %s so nothing is lost",
                  path, exc, broken)
        try:
            path.replace(broken)
        except OSError:
            pass
        return []
    if data is None:
        return []
    if not isinstance(data, list):
        log.error("%s should be a YAML list; ignoring its contents", path)
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _write_list(path: Path, header: str, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=100) \
        if entries else "[]\n"
    temp = path.with_suffix(".tmp")
    temp.write_text(header + body, encoding="utf-8")
    temp.replace(path)


def load_pending() -> list[dict]:
    return _read_list(PENDING_PATH)


def save_pending(entries: list[dict]) -> None:
    _write_list(PENDING_PATH, PENDING_HEADER, entries)


def load_bank() -> dict[str, dict]:
    """Saved answers keyed by the normalised question."""
    bank: dict[str, dict] = {}
    for entry in _read_list(BANK_PATH):
        question = entry.get("question")
        if not question:
            continue
        bank[key(question)] = entry
    return bank


def save_bank(entries: list[dict]) -> None:
    _write_list(BANK_PATH, BANK_HEADER, entries)


def pending_count() -> int:
    return sum(1 for e in load_pending() if not str(e.get("answer") or "").strip())


def job_ref(job, board: str) -> dict:
    return {
        "job_id": str(getattr(job, "job_id", "") or ""),
        "title": getattr(job, "title", "") or "",
        "company": getattr(job, "company", "") or "",
        "url": getattr(job, "url", "") or "",
        "board": board,
    }


def record(question: str, options: list[str] | None, job, board: str = "naukri") -> bool:
    """Put a question on the waiting list. Returns True if it was not there yet.

    The same question asked by a second job is folded into the existing entry,
    so you answer it once. A job blocked on a question is listed under it, and
    that list is what the next run re-attempts once you have answered.
    """
    question = (question or "").strip()
    if not question:
        return False
    entries = load_pending()
    k = key(question)
    ref = job_ref(job, board)
    for entry in entries:
        if key(entry.get("question", "")) != k:
            continue
        jobs = entry.setdefault("jobs", [])
        if not any(j.get("job_id") == ref["job_id"] for j in jobs if isinstance(j, dict)):
            jobs.append(ref)
        if options and not entry.get("options"):
            entry["options"] = list(options)
        save_pending(entries)
        return False
    entries.append({
        "question": question,
        "options": list(options or []),
        "answer": "",
        "board": board,
        "first_asked": date.today().isoformat(),
        "jobs": [ref],
    })
    save_pending(entries)
    log.info("New screening question saved for you: %r", question[:80])
    return True


def absorb() -> tuple[list[dict], list[dict]]:
    """Move every answered entry from questions.yaml into the bank.

    Returns (entries absorbed, jobs now free to retry). A job is free only
    when no *other* pending question still lists it - re-opening a job you
    have answered one question for, only to be stopped by a second unanswered
    one, would just churn.
    """
    entries = load_pending()
    answered = [e for e in entries if str(e.get("answer") or "").strip()]
    if not answered:
        return [], []

    bank = _read_list(BANK_PATH)
    stamp = datetime.now().isoformat(timespec="seconds")
    for entry in answered:
        k = key(entry.get("question", ""))
        bank = [b for b in bank if key(b.get("question", "")) != k]
        answer = str(entry["answer"]).strip()
        item = {"question": entry["question"], "answer": answer,
                "options": entry.get("options") or [], "answered_at": stamp}
        if answer.lower() == SKIP:
            item["answer"] = SKIP
        bank.append(item)
    save_bank(bank)

    remaining = [e for e in entries if e not in answered]
    save_pending(remaining)

    still_blocked = {
        j.get("job_id") for e in remaining for j in (e.get("jobs") or []) if isinstance(j, dict)
    }
    retry: dict[str, dict] = {}
    for entry in answered:
        if str(entry["answer"]).strip().lower() == SKIP:
            continue
        for job in entry.get("jobs") or []:
            if isinstance(job, dict) and job.get("job_id") and job["job_id"] not in still_blocked:
                retry[job["job_id"]] = job
    log.info("Absorbed %d answered question(s) into the bank; %d job(s) to retry",
             len(answered), len(retry))
    return answered, list(retry.values())


def lookup(question: str, bank: dict[str, dict] | None) -> dict | None:
    """The saved answer for a question, or None."""
    if not bank:
        return None
    return bank.get(key(question))


def answer_interactively() -> int:
    """Walk through the waiting questions in the terminal. Returns how many
    were answered."""
    entries = load_pending()
    waiting = [e for e in entries if not str(e.get("answer") or "").strip()]
    if not waiting:
        print("\n  No screening questions are waiting for you.\n")
        return 0

    print(f"\n  {len(waiting)} question(s) waiting. Press Enter to leave one for later,"
          f" type 'skip' to never answer it.\n")
    answered = 0
    for index, entry in enumerate(waiting, 1):
        jobs = entry.get("jobs") or []
        print(f"  [{index}/{len(waiting)}] {entry.get('question')}")
        for option in entry.get("options") or []:
            print(f"        - {option}")
        for job in jobs[:3]:
            if isinstance(job, dict):
                print(f"        asked by: {job.get('title')} - {job.get('company')} ({job.get('board')})")
        if len(jobs) > 3:
            print(f"        ... and {len(jobs) - 3} more job(s)")
        try:
            reply = input("      answer: ").strip()
        except EOFError:
            print()
            break
        if reply:
            entry["answer"] = reply
            answered += 1
        print()

    save_pending(entries)
    absorbed, retry = absorb()
    print(f"  Saved {len(absorbed)} answer(s) to data/jobs/answer_bank.yaml."
          f" {len(retry)} job(s) will be re-attempted on the next run"
          f" (or now: python main.py --jobs-export --apply-found --yes).\n")
    return answered
