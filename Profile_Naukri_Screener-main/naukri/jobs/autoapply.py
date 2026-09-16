"""Apply to what a scan found, on both boards, without you.

Runs at the end of `--jobs-export --apply` (which is what the scheduled scan
does). The scan has already searched, scored and ranked the day's openings;
this walks that list and clicks Apply on every one it can:

    Naukri     one-click postings, and questionnaire postings whose questions
               can be answered from your profile, jobs.yaml and the answer
               bank. "Apply on company site" postings are left for you.
    LinkedIn   Easy Apply postings only. External-apply postings are left.

A question neither your profile nor your saved answers can settle stops that
job, saves the question to data/jobs/questions.yaml, and the job waits. Answer
it (python main.py --answer-questions, or edit the file) and the next run
absorbs the answer and re-attempts every job that was waiting on it.

Everything is recorded in data/jobs/ledger.json, so a job is never applied to
twice and the daily caps in jobs.yaml (`max_auto_applies` for Naukri,
`linkedin_max_applies_per_day` for LinkedIn) hold across every run of the day.

PACE. Both boards watch for bursts, and a restriction costs the account. So a
run applies to at most `per_run` jobs per board (the scheduler passes 5 for
the morning and afternoon runs, 10 for the evening and night ones), with a
long, uneven pause between applications - about a minute on Naukri, longer on
LinkedIn - the way a person working through a list would. What a run does not
get to stays in the backlog: every job the last two days' scans listed and the
ledger has not settled is a candidate again on the next run, so the small
batches drain the list overnight instead of dropping it.
"""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import date, timedelta
from pathlib import Path

from . import answers as answers_mod
from . import applications, applier, config as config_mod, linkedin as linkedin_mod, linkedin_apply, questions
from .ledger import Ledger
from .model import Job

log = logging.getLogger("naukri.jobs.autoapply")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"

# Seconds between two applications. Long and uneven on purpose - see PACE.
NAUKRI_PAUSE = (35.0, 80.0)
LINKEDIN_PAUSE = (50.0, 110.0)

# Ledger statuses that mean "leave this job alone".
DONE = {"applied", "skipped", "offsite", "questionnaire-declined"}
# Waiting on an answer from you. Re-attempted only via questions.absorb().
WAITING = "questionnaire-pending"


def _applied_today(ledger: Ledger, board: str) -> int:
    stamp = date.today().isoformat()
    count = 0
    for job_id, entry in ledger.entries.items():
        if entry.get("status") != "applied" or not str(entry.get("at", "")).startswith(stamp):
            continue
        is_linkedin = str(job_id).startswith("linkedin:")
        if (board == "linkedin") == is_linkedin:
            count += 1
    return count


def backlog(days: int = 2) -> tuple[list[Job], list[dict]]:
    """Naukri jobs and LinkedIn cards from the last `days` scans.

    Read from data/jobs/results-<date>.json, oldest first so today's list
    wins on a duplicate. Only what the ledger has not settled is worth
    returning, but that filter is applied by run(), which owns the ledger.
    """
    jobs: dict[str, Job] = {}
    cards: dict[str, dict] = {}
    for offset in range(days - 1, -1, -1):
        day = (date.today() - timedelta(days=offset)).isoformat()
        path = JOBS_DIR / f"results-{day}.json"
        if not path.exists():
            continue
        try:
            results = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read %s (%s)", path, exc)
            continue
        for rec in results.get("naukri") or []:
            fields = {k: v for k, v in rec.items() if k in Job.__dataclass_fields__}
            if not fields.get("job_id") or not fields.get("url"):
                continue
            job = Job(**fields)
            job.score = rec.get("score") or 0
            jobs[job.job_id] = job
        for card in results.get("linkedin") or []:
            if card.get("job_id") and card.get("url"):
                cards[str(card["job_id"])] = dict(card)
    return list(jobs.values()), list(cards.values())


def _card_job(card: dict) -> Job:
    """A ledger-able record for a LinkedIn card."""
    raw = str(card.get("job_id") or "")
    job_id = raw if raw.startswith("linkedin:") else f"linkedin:{raw}"
    return Job(job_id=job_id, title=card.get("title") or "", company=card.get("company") or "",
               url=card.get("url") or "", source="linkedin")


def _record(ledger: Ledger, job, status: str, note: str, board: str, capture: dict) -> None:
    """Map an apply outcome onto the ledger, saving any blocking question."""
    if status == "applied":
        ledger.record(job, "applied", note)
    elif status == "would-apply":
        return
    elif status == "already" and ledger.status(job.job_id) == "unconfirmed":
        # Our own earlier click, confirmed on the revisit. Counts as ours, and
        # as one of today's applications for the cap.
        ledger.record(job, "applied", f"confirmed on a later visit ({note})")
    elif status in ("already", "no-button"):
        ledger.record(job, "skipped", note)
    elif status == "offsite":
        ledger.record(job, "offsite", note)
    elif status == "questionnaire":
        if capture.get("question"):
            questions.record(capture["question"], capture.get("options") or [], job, board)
            ledger.record(job, WAITING, note)
        else:
            # Stopped by a rule that says "skip" or a skipped bank answer:
            # asking you again would be pointless.
            ledger.record(job, "questionnaire-declined", note)
    else:
        # questionnaire-failed / unconfirmed / error: worth another go later.
        ledger.record(job, status, note)


def run(kept: list, cards: list[dict], config: dict, profile: dict,
        headless: bool = False, dry_run: bool = True,
        per_run: int | None = None, include_backlog: bool = True,
        project: str = "naukri") -> dict:
    """Apply across both boards. Returns {row_id: {status, note}} plus
    a "_summary" entry with the counts.

    `kept` are the scan's Naukri Job objects (scored), `cards` its LinkedIn
    cards. Row ids match the tracker page: "naukri:<id>" / "linkedin:<id>".
    `per_run` caps applications per board for this run (None = only the
    daily caps apply). `include_backlog` adds the last two days' unsettled
    listings after this scan's own, so small runs drain the list over time.
    `project` tags the applications log with which search found the jobs.
    """
    from playwright.sync_api import sync_playwright

    from ..session import DEFAULT_STATE, open_profile

    facts = answers_mod.build_facts(profile, config)
    facts["_bank"] = questions.load_bank()
    phone = str(facts.get("stated_phone") or "").strip() or None
    ledger = Ledger()
    outcomes: dict[str, dict] = {}
    summary = {"dry_run": dry_run, "naukri": {}, "linkedin": {}, "questions_saved": 0,
               "retried": 0, "pending_questions": 0, "per_run": per_run, "backlog": 0}

    if include_backlog:
        old_jobs, old_cards = backlog()
        have_jobs = {j.job_id for j in kept}
        have_cards = {str(c.get("job_id")) for c in cards}
        extra_jobs = [j for j in old_jobs if j.job_id not in have_jobs]
        extra_cards = [c for c in old_cards if str(c.get("job_id")) not in have_cards]
        kept = list(kept) + extra_jobs
        cards = list(cards) + extra_cards
        summary["backlog"] = len(extra_jobs) + len(extra_cards)

    # Answers you gave since the last run, and the jobs they unblock.
    absorbed, retry = questions.absorb()
    retry_naukri = [Job(job_id=j["job_id"], title=j.get("title") or "", company=j.get("company") or "",
                        url=j.get("url") or "")
                    for j in retry if j.get("board") != "linkedin" and j.get("url")]
    retry_cards = [{"job_id": j["job_id"], "title": j.get("title"), "company": j.get("company"),
                    "url": j.get("url"), "easy_apply": True}
                   for j in retry if j.get("board") == "linkedin" and j.get("url")]
    summary["retried"] = len(retry_naukri) + len(retry_cards)
    if absorbed:
        log.info("%d answered question(s) absorbed; re-attempting %d job(s)",
                 len(absorbed), summary["retried"])
    before = questions.pending_count()

    # ---------------------------------------------------------------- Naukri
    min_score = float(config.get("scan_apply_min_score") or 0)
    budget = max(0, int(config.get("max_auto_applies") or 0) - _applied_today(ledger, "naukri"))
    if per_run is not None:
        budget = min(budget, max(0, int(per_run)))
    naukri_jobs = []
    for job in sorted(kept, key=lambda j: getattr(j, "score", 0) or 0, reverse=True):
        status = ledger.status(job.job_id)
        if status in DONE or status == WAITING:
            continue
        if (getattr(job, "score", 0) or 0) < min_score:
            continue
        naukri_jobs.append(job)
    for job in retry_naukri:
        if ledger.status(job.job_id) == WAITING and job.job_id not in {j.job_id for j in naukri_jobs}:
            naukri_jobs.append(job)

    counts = summary["naukri"]
    if naukri_jobs and budget <= 0:
        log.info("Naukri: daily cap of %s already reached; %d job(s) left for tomorrow",
                 config.get("max_auto_applies"), len(naukri_jobs))
    if naukri_jobs and budget > 0:
        log.info("Naukri: applying to up to %d of %d job(s)%s", budget, len(naukri_jobs),
                 " (dry run)" if dry_run else "")
        with sync_playwright() as p:
            browser, _ctx, page = open_profile(p, DEFAULT_STATE, headless=headless)
            try:
                for job in naukri_jobs:
                    if budget <= 0:
                        break
                    capture: dict = {}
                    if getattr(job, "company_apply", False):
                        status, note = "offsite", "applies on the company's own site"
                    else:
                        status, note = applier.apply_to(page, job, dry_run=dry_run,
                                                        facts=facts, capture=capture)
                        _record(ledger, job, status, note, "naukri", capture)
                        if status == "questionnaire" and capture.get("question"):
                            summary["questions_saved"] += 1
                    if status == "offsite":
                        ledger.record(job, "offsite", note)
                    if not dry_run:
                        applications.record("naukri", job, status, note, capture,
                                            dry_run=False, per_run=per_run, project=project)
                    counts[status] = counts.get(status, 0) + 1
                    outcomes[f"naukri:{job.job_id}"] = {"status": status, "note": note}
                    log.info("[naukri %s] %s @ %s - %s", status, job.title, job.company, note)
                    if status in ("applied", "would-apply"):
                        budget -= 1
                    if not dry_run and status not in ("offsite",) and budget > 0:
                        time.sleep(random.uniform(*NAUKRI_PAUSE))
            finally:
                browser.close()
        if not dry_run:
            ledger.save()

    # -------------------------------------------------------------- LinkedIn
    counts = summary["linkedin"]
    if config.get("linkedin_easy_apply", True):
        li_budget = max(0, int(config.get("linkedin_max_applies_per_day") or 0)
                        - _applied_today(ledger, "linkedin"))
        if per_run is not None:
            li_budget = min(li_budget, max(0, int(per_run)))
        li_cards = []
        seen_ids = set()
        for card in list(cards) + retry_cards:
            if not card.get("easy_apply") or not card.get("url"):
                continue
            job = _card_job(card)
            if job.job_id in seen_ids:
                continue
            status = ledger.status(job.job_id)
            if status in DONE:
                continue
            if status == WAITING and job.job_id not in {c["job_id"] for c in retry_cards}:
                continue
            seen_ids.add(job.job_id)
            li_cards.append((card, job))
        if li_cards and li_budget <= 0:
            log.info("LinkedIn: daily cap of %s already reached; %d job(s) left for tomorrow",
                     config.get("linkedin_max_applies_per_day"), len(li_cards))
        if li_cards and li_budget > 0:
            log.info("LinkedIn: Easy Apply to up to %d of %d job(s)%s", li_budget, len(li_cards),
                     " (dry run)" if dry_run else "")
            try:
                with sync_playwright() as p:
                    browser, _ctx, page = linkedin_mod.open_session(p, headless=headless)
                    try:
                        for card, job in li_cards:
                            if li_budget <= 0:
                                break
                            capture = {}
                            status, note = linkedin_apply.apply_to(
                                page, card, facts, dry_run=dry_run, phone=phone, capture=capture)
                            _record(ledger, job, status, note, "linkedin", capture)
                            if status == "questionnaire" and capture.get("question"):
                                summary["questions_saved"] += 1
                            if not dry_run:
                                applications.record("linkedin", job, status, note, capture,
                                                    dry_run=False, per_run=per_run, project=project)
                            counts[status] = counts.get(status, 0) + 1
                            outcomes[job.job_id] = {"status": status, "note": note}
                            log.info("[linkedin %s] %s @ %s - %s", status, job.title, job.company, note)
                            if status in ("applied", "would-apply"):
                                li_budget -= 1
                            if not dry_run and li_budget > 0:
                                time.sleep(random.uniform(*LINKEDIN_PAUSE))
                    finally:
                        browser.close()
            except linkedin_mod.NotLoggedIn as exc:
                log.warning("LinkedIn applies skipped: %s", exc)
                counts["skipped-not-logged-in"] = len(li_cards)
            if not dry_run:
                ledger.save()

    summary["pending_questions"] = questions.pending_count()
    summary["new_questions"] = max(0, summary["pending_questions"] - before)
    if not dry_run:
        try:
            summary["applications_page"] = str(applications.build_page())
        except Exception as exc:  # the page is a convenience; the log is the record
            log.warning("Could not rebuild the applications page: %s", exc)
    outcomes["_summary"] = summary
    return outcomes


def summarise(outcomes: dict) -> str:
    """Console lines for the end of a scan."""
    summary = (outcomes or {}).get("_summary")
    if not summary:
        return ""
    verb = "would apply to" if summary["dry_run"] else "applied to"

    def line(board: str, counts: dict) -> str:
        sent = counts.get("applied", 0) + counts.get("would-apply", 0)
        rest = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())
                         if k not in ("applied", "would-apply"))
        return f"  {board}: {verb} {sent}" + (f"  ({rest})" if rest else "")

    lines = ["", "  Auto-apply:", line("Naukri", summary["naukri"]), line("LinkedIn", summary["linkedin"])]
    if summary.get("per_run") is not None:
        lines.append(f"  Limit this run: {summary['per_run']} per board"
                     f" (backlog from earlier scans: {summary.get('backlog', 0)} listing(s))")
    if summary.get("applications_page"):
        lines.append(f"  Every attempt, with the answers given: {summary['applications_page']}")
    if summary.get("retried"):
        lines.append(f"  Re-attempted {summary['retried']} job(s) you answered questions for")
    if summary.get("pending_questions"):
        lines += [
            f"  {summary['pending_questions']} screening question(s) waiting for you"
            f" ({summary.get('new_questions', 0)} new): data/jobs/questions.yaml",
            "  Answer them with:  python main.py --answer-questions",
        ]
    if summary["dry_run"]:
        lines.append("  Dry run - nothing was submitted. Add --yes to apply for real.")
    lines.append("")
    return "\n".join(lines)
