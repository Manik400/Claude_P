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
        if entry.get("answered_by"):
            item["learned"] = entry["answered_by"]
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


# ------------------------------------------------------------------ same question, other words
#
# "DOB (Date of Birth)" answered once must also answer "Date of birth", and "LinkedIn
# Profile" must answer "Please provide your LinkedIn profile URL". lookup() only takes
# the exact wording, so find_similar() tries three stricter-to-looser ways, each one
# refusing to stretch an answer across a real difference (Java vs JavaScript, current
# vs expected CTC):
#
#   1. the same personal field (FIELDS), for short questions that name one
#   2. the same words once filler ("please", "your", "url", "profile") is dropped
#   3. the local model agreeing the two ask for the same fact - only for close
#      candidates, and never when they name different skills or numbers

FIELDS: list[tuple[str, str]] = [
    ("date_of_birth", r"\bd\.?\s?o\.?\s?b\b|date\s*of\s*birth|birth\s*date|birthday|born\s+on"),
    ("gender", r"\bgender\b"),
    ("marital_status", r"marital"),
    ("nationality", r"nationality|citizenship"),
    ("middle_name", r"middle\s*name"),
    ("father_name", r"father'?s?\s+name"),
    ("pan", r"\bpan\s*(card|number|no)\b|^\W*pan\W*$"),
    ("pincode", r"pin\s*code|postal\s*code|\bzip\b"),
    ("linkedin", r"linked\s*in"),
    ("github", r"git\s*hub"),
    ("portfolio", r"portfolio|personal\s+(website|site)"),
    ("alternate_phone", r"alternate\s+(phone|mobile|contact|number)"),
    ("graduation_year", r"(graduation|passing|passed\s*out)\s*year|year\s+of\s+(graduation|passing)"),
    ("highest_qualification", r"highest\s+(qualification|education|degree)"),
]
# A question about one of these is not a personal-field question ("years with LinkedIn Ads").
NOT_A_FIELD = re.compile(r"\byears?\b|experience|how many|how long|proficien|rate\b", re.I)
FILLER = set("""a an the your you yours please kindly enter provide mention share give specify what whats
is are was were do does did of for to in on at with and or my me i by as be this that it its here below if
have has any url link links address details detail id profile page type fill write add input number no
how many much work working currently""".split())


def _tokens(question: str) -> set[str]:
    words = key(re.sub(r"\([^)]*\)", " ", question or "") or question).split()
    out = set()
    for w in words:
        w = w.strip(".")
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w:
            out.add(w)
    return out


def field_of(question: str) -> str | None:
    """The personal field a short question asks for, when it asks for exactly one."""
    text = re.sub(r"\s+", " ", question or "").strip()
    if not text or len(text.split()) > 16 or NOT_A_FIELD.search(text):
        return None
    hits = [name for name, pattern in FIELDS if re.search(pattern, text, re.I)]
    return hits[0] if len(hits) == 1 else None


_VOCAB: set[str] = set()


def _skill_words() -> set[str]:
    """Single words of job-hunt's skills vocabulary (python, django, kafka ...), read once."""
    if not _VOCAB:
        path = ROOT.parent / "job-hunt" / "assets" / "skills_vocab.txt"
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    for name in line.split("|"):
                        _VOCAB.update(w for w in key(name).split() if len(w) > 1)
        except OSError:
            pass
        _VOCAB.add("-")     # loaded (possibly empty): do not read again
    return _VOCAB


def _distinct(token: str, protect: set[str]) -> bool:
    """A word two questions must share to share an answer: a skill, a number, a version."""
    return (bool(re.search(r"[\d+#]", token)) or "." in token or token in protect
            or token in _skill_words() or (token + "s") in _skill_words())


_similar_cache: dict[tuple, tuple | None] = {}


def find_similar(question: str, bank: dict[str, dict] | None, options: list[str] | None = None,
                 protect: set[str] | None = None, use_model: bool = True) -> tuple[dict, str] | None:
    """(saved entry, how it matched) for a question worded differently from a saved one, or None."""
    if not bank or not question:
        return None
    cache_key = (key(question), tuple(options or ()), len(bank))
    if cache_key in _similar_cache:
        return _similar_cache[cache_key]
    protect = {p.lower() for p in (protect or ())}
    result = None
    field = field_of(question)
    if field:
        for entry in bank.values():
            if field_of(entry.get("question", "")) == field and str(entry.get("answer", "")).strip():
                result = (entry, f"same {field.replace('_', ' ')} question")
                break
    mine = _tokens(question)
    if result is None and mine:
        close = []
        for entry in bank.values():
            theirs = _tokens(entry.get("question", ""))
            if not theirs or not (mine & theirs):
                continue
            diff = mine ^ theirs
            if all(t in FILLER for t in diff):
                result = (entry, "same question, other words")
                break
            overlap = len(mine & theirs) / len(mine | theirs)
            if overlap >= 0.4 and not any(_distinct(t, protect) for t in diff):
                close.append((overlap, entry))
        if result is None and close and use_model:
            try:
                from naukri import localai
                ok = localai.available("llm")
            except Exception:  # noqa: BLE001 - no model: the question waits for you, as before
                ok = False
            for _overlap, entry in sorted(close, key=lambda c: -c[0])[:1] if ok else []:   # one CPU call, the closest
                verdict = localai.same_question(question, entry["question"], options)
                if verdict and verdict["same"] and verdict["confidence"] >= 0.85:
                    result = (entry, "the local model matched it to a saved question")
                    break
    _similar_cache[cache_key] = result
    return result


def self_answer(resolve) -> int:
    """Answer waiting questions that the facts can settle now (a DOB you have since saved
    under another wording, a city the profile holds). `resolve(question, options)` is
    answers.resolve without the model. Returns how many; absorb() then frees their jobs."""
    entries = load_pending()
    n = 0
    for entry in entries:
        if str(entry.get("answer") or "").strip() or not entry.get("question"):
            continue
        answer, why = resolve(entry["question"], entry.get("options") or [])
        if answer is None or not str(answer).strip():
            continue
        entry["answer"], entry["answered_by"] = str(answer), why
        n += 1
    if n:
        save_pending(entries)
        log.info("%d waiting question(s) answered from your facts / saved answers", n)
    return n


def answered(fragment: str, bank: dict[str, dict] | None = None) -> bool:
    """Has this question (possibly cut short in a note) been answered - in the bank, or
    typed into questions.yaml and not absorbed yet?"""
    bank = dict(bank if bank is not None else load_bank())
    for entry in load_pending():
        if str(entry.get("answer") or "").strip() and entry.get("question"):
            bank[key(entry["question"])] = entry
    k = key(fragment)
    if not k:
        return False
    hit = bank.get(k) or next((e for bk, e in bank.items() if len(k) >= 20 and bk.startswith(k)), None) \
        or (find_similar(fragment, bank, use_model=False) or (None,))[0]
    return bool(hit) and str(hit.get("answer", "")).strip().lower() not in ("", SKIP)


def similar_entries(question: str, bank: dict[str, dict] | None, n: int = 6) -> list[dict]:
    """The saved answers whose questions share the most words with this one (examples for the model)."""
    mine = _tokens(question) - FILLER
    if not bank or not mine:
        return []
    scored = []
    for entry in bank.values():
        answer = str(entry.get("answer") or "").strip()
        if not answer or answer.lower() == SKIP:
            continue
        shared = len(mine & (_tokens(entry.get("question", "")) - FILLER))
        if shared:
            scored.append((shared, entry))
    return [e for _s, e in sorted(scored, key=lambda s: -s[0])[:n]]


def learn(items: list[dict]) -> int:
    """Save answers the local model gave in a form that then went through, so the same
    question is answered from the bank next time (no model call, same answer).
    Only short factual answers - written paragraphs are per job and are not reused."""
    fresh = [i for i in items if i.get("question") and str(i.get("answer") or "").strip()
             and len(str(i["answer"])) <= 80]
    if not fresh:
        return 0
    bank = _read_list(BANK_PATH)
    have = {key(b.get("question", "")) for b in bank}
    stamp = datetime.now().isoformat(timespec="seconds")
    added = 0
    for item in fresh:
        k = key(item["question"])
        if k in have:
            continue
        bank.append({"question": item["question"], "answer": str(item["answer"]).strip(),
                     "options": list(item.get("options") or []), "answered_at": stamp,
                     "learned": item.get("source") or "local model, form submitted"})
        have.add(k)
        added += 1
    if added:
        save_bank(bank)
        log.info("Learned %d answer(s) from submitted forms into %s", added, BANK_PATH.name)
    return added


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
