"""The daily run: search, score, apply to the strong matches, queue the rest.

    search  ->  score  ->  rank  ->  split
                                      |-- auto-apply   score >= auto_apply_min_score
                                      |                and one click completes it
                                      |-- review queue everything else above
                                      |                review_min_score
                                      `-- drop         the rest

Two caps bound the auto-apply arm: `max_auto_applies` per run, and whatever has
already been sent today according to the ledger. The second matters because a
re-run after a crash would otherwise start the day's quota over.
"""
from __future__ import annotations

import json
import logging
import re
import random
import time
from datetime import date
from pathlib import Path

from . import answers, applier, config as config_mod, score as score_mod, search
from .ledger import Ledger

log = logging.getLogger("naukri.jobs.daily")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"
QUEUE_PATH = JOBS_DIR / "review_queue.json"


def run(headless: bool = False, dry_run: bool = True, config_overrides: dict | None = None) -> dict:
    """Execute one daily cycle. Returns a summary dict."""
    from playwright.sync_api import sync_playwright

    from ..session import DEFAULT_STATE, open_profile

    profile = config_mod.load_profile()
    config = config_mod.load(profile=profile)
    if config_overrides:
        config.update(config_overrides)

    log.info(
        "Profile: %s, %s, %s years",
        profile.get("name"), profile.get("location"), config.get("profile_years"),
    )

    # Facts are only built when answering is switched on. Passing None to the
    # applier is what makes it close every questionnaire unanswered, so this
    # single value is the on/off switch for the whole behaviour.
    facts = None
    if config.get("answer_questionnaires"):
        facts = answers.build_facts(profile, config)
        missing = [k for k in ("expected_ctc_lpa", "willing_to_relocate") if facts.get(k) is None]
        log.info("Answering screening questions from facts: %s",
                 ", ".join(f"{k}={v}" for k, v in facts.items()
                           if k not in ("skills", "skill_years") and v is not None))
        if missing:
            log.warning("No value for %s - questions needing those will be queued. "
                        "Set them under `answers:` in jobs.yaml.", ", ".join(missing))

    ledger = Ledger()
    already_today = ledger.applied_on(date.today())
    budget = max(0, int(config["max_auto_applies"]) - already_today)
    if already_today:
        log.info("%d application(s) already sent today; budget for this run: %d",
                 already_today, budget)

    summary: dict = {
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dry_run": dry_run,
        "collected": 0,
        "considered": 0,
        "applied": [],
        "queued": [],
        "outcomes": {},
    }

    with sync_playwright() as p:
        # Headed, always: Naukri sits behind Akamai, which serves "Access
        # Denied" to headless Chromium. open_profile also validates the saved
        # session up front, so an expired login fails here rather than midway
        # through applying.
        browser, _context, page = open_profile(p, DEFAULT_STATE, headless=headless)
        try:
            jobs = search.gather(page, config)
            summary["collected"] = len(jobs)

            fresh = [j for j in jobs if not ledger.is_terminal(j.job_id)]
            log.info("%d of %d are new (rest already handled)", len(fresh), len(jobs))

            for job in fresh:
                score_mod.score(job, config)
            fresh.sort(key=lambda j: j.score, reverse=True)

            shortlist = [j for j in fresh if j.score >= config["review_min_score"]]
            shortlist = shortlist[: int(config["daily_target"])]
            summary["considered"] = len(shortlist)
            log.info("%d job(s) above the review threshold of %s",
                     len(shortlist), config["review_min_score"])

            queue = []
            attempts = 0
            attempt_cap = config.get("max_apply_attempts")
            for job in shortlist:
                strong = job.score >= config["auto_apply_min_score"]
                if attempt_cap is not None and attempts >= attempt_cap:
                    queue.append(_queue_entry(job, "attempt cap reached for this run"))
                    continue

                if not strong:
                    queue.append(_queue_entry(job, "below auto-apply threshold"))
                    continue
                # An off-site posting is a bespoke form on someone else's
                # domain - never attemptable. A questionnaire is attemptable
                # only when answering is switched on and we have facts for it.
                if job.company_apply:
                    reason = "applies on the company's own site"
                    queue.append(_queue_entry(job, reason))
                    ledger.record(job, "offsite", reason)
                    continue
                if job.has_questionnaire and facts is None:
                    reason = "has a screening questionnaire"
                    queue.append(_queue_entry(job, reason))
                    ledger.record(job, "queued", reason)
                    continue
                if budget <= 0:
                    queue.append(_queue_entry(job, "daily apply cap reached"))
                    continue

                attempts += 1
                status, note = applier.apply_to(page, job, dry_run=dry_run, facts=facts)
                summary["outcomes"][status] = summary["outcomes"].get(status, 0) + 1
                log.info("[%s] %s @ %s (%s) - %s",
                         status, job.title, job.company, job.score, note)

                if status == "applied":
                    budget -= 1
                    summary["applied"].append(_queue_entry(job, note))
                    ledger.record(job, "applied", note)
                elif status == "would-apply":
                    budget -= 1
                    summary["applied"].append(_queue_entry(job, note))
                elif status == "questionnaire":
                    # A genuine refusal: it asked something we cannot know.
                    # Terminal - retrying tomorrow would ask the same thing.
                    queue.append(_queue_entry(job, f"screening question needs you: {note}"))
                    ledger.record(job, "questionnaire-declined", note)
                elif status == "questionnaire-failed":
                    # Mechanical failure, not a refusal. Left non-terminal so a
                    # later run retries it once the cause is fixed.
                    queue.append(_queue_entry(job, f"questionnaire not completed: {note}"))
                    ledger.record(job, "questionnaire-failed", note)
                elif status in ("already", "offsite", "no-button"):
                    ledger.record(job, "skipped" if status != "offsite" else "offsite", note)
                else:
                    # error / unconfirmed: leave non-terminal so it can be retried.
                    ledger.record(job, status, note)
                    queue.append(_queue_entry(job, f"{status}: {note}"))

                if not dry_run:
                    time.sleep(random.uniform(6.0, 14.0))

            summary["queued"] = queue
        finally:
            browser.close()

    if not dry_run:
        ledger.save()

    summary["day_totals"] = _write_outputs(summary, config, ledger)
    return summary


def _queue_entry(job, reason: str) -> dict:
    return {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "url": job.url,
        "score": job.score,
        "location": job.location,
        "experience": job.experience_label,
        "salary": job.salary_label,
        "posted": job.posted_label,
        "source": job.source,
        "reason": reason,
        "why": score_mod.explain(job),
    }


def _runs_path(day: date | None = None) -> Path:
    return JOBS_DIR / f"runs-{(day or date.today()).isoformat()}.json"


def _load_runs(day: date | None = None) -> list[dict]:
    path = _runs_path(day)
    if not path.exists():
        return []
    try:
        runs = json.loads(path.read_text(encoding="utf-8"))
        return runs if isinstance(runs, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Run log at %s unreadable (%s); starting a fresh one", path, exc)
        return []


def _merge_queue(existing: list[dict], new: list[dict], ledger: Ledger) -> list[dict]:
    """Combine this run's queue with what earlier runs today already queued.

    The agent runs several times a day, so the queue has to accumulate. It also
    has to shed entries that a later run resolved - a job queued at 09:00 for
    being below the bar, then applied to at 17:00 after its score moved, should
    not still be sitting in the queue asking to be reviewed.
    """
    merged: dict[str, dict] = {}
    for entry in list(existing) + list(new):
        job_id = entry.get("job_id")
        if not job_id or ledger.is_terminal(job_id):
            continue
        merged[job_id] = entry  # later runs win
    return sorted(merged.values(), key=lambda e: e.get("score") or 0, reverse=True)


def _write_outputs(summary: dict, config: dict, ledger: Ledger) -> dict:
    """Persist this run, fold it into the day's totals, rewrite the report."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    previous = _load_runs()
    existing_queue = []
    if QUEUE_PATH.exists():
        try:
            loaded = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
            existing_queue = loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError):
            existing_queue = []
    # Only carry the queue forward within the same day.
    if not previous:
        existing_queue = []

    summary["queued"] = _merge_queue(existing_queue, summary["queued"], ledger)

    runs = previous + [summary]
    _runs_path().write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
    QUEUE_PATH.write_text(
        json.dumps(summary["queued"], indent=2, ensure_ascii=False), encoding="utf-8"
    )

    totals = day_totals(runs)
    report = JOBS_DIR / f"report-{date.today().isoformat()}.md"
    report.write_text(render_report(runs, config), encoding="utf-8")

    log.info("Run %d of the day. Today: %d matches found, %d applications sent.",
             len(runs), totals["found"], totals["applied"])
    log.info("Queue -> %s", QUEUE_PATH)
    log.info("Report -> %s", report)
    return totals


def day_totals(runs: list[dict]) -> dict:
    """Aggregate every run of the day. Applications are counted by job, not by
    run, so a job seen twice is never counted twice."""
    applied_ids, queued_ids, collected = set(), set(), 0
    outcomes: dict[str, int] = {}
    for run_summary in runs:
        collected += run_summary.get("collected", 0)
        for entry in run_summary.get("applied", []):
            applied_ids.add(entry.get("job_id"))
        for status, count in (run_summary.get("outcomes") or {}).items():
            outcomes[status] = outcomes.get(status, 0) + count
    for entry in runs[-1].get("queued", []) if runs else []:
        queued_ids.add(entry.get("job_id"))
    return {
        "runs": len(runs),
        "collected": collected,
        "found": len(applied_ids) + len(queued_ids),
        "applied": len(applied_ids),
        "queued": len(queued_ids),
        "outcomes": outcomes,
    }


def render_report(runs: list[dict], config: dict) -> str:
    """The day's report, rebuilt from every run so far."""
    totals = day_totals(runs)
    latest = runs[-1]
    dry = all(r.get("dry_run") for r in runs)

    lines = [
        f"# Naukri job agent - {date.today().isoformat()}",
        "",
        f"**{totals['found']} matches found - {totals['applied']} applied to"
        f" - {totals['queued']} waiting for you.**",
        "",
        f"- Runs today: {totals['runs']} (latest {latest['ran_at']})",
        f"- Mode: {'dry run - nothing submitted' if dry else 'live'}",
        f"- Listings scanned: {totals['collected']}",
        f"- Thresholds: apply at {config['auto_apply_min_score']},"
        f" review at {config['review_min_score']}, cap {config['max_auto_applies']}/day",
        "",
    ]

    verb = "Would apply" if dry else "Applied"
    applied = [e for run in runs for e in run.get("applied", [])]
    lines += [f"## {verb} ({len(applied)})", ""]
    if applied:
        for entry in applied:
            lines += [
                f"- **{entry['title']}** - {entry['company']} ({entry['score']})",
                f"  {entry['location'] or '?'} | {entry['experience'] or '?'} | {entry['salary'] or '?'} | {entry['posted'] or '?'}",
                f"  <{entry['url']}>",
                f"  _{entry['why']}_",
            ]
    else:
        lines.append("_Nothing cleared the auto-apply bar._")

    queued = latest.get("queued", [])
    lines += ["", f"## For you to review ({len(queued)})", ""]
    if queued:
        for entry in queued:
            lines += [
                f"- **{entry['title']}** - {entry['company']} ({entry['score']}) - {entry['reason']}",
                f"  {entry['location'] or '?'} | {entry['experience'] or '?'} | {entry['salary'] or '?'} | {entry['posted'] or '?'}",
                f"  <{entry['url']}>",
            ]
    else:
        lines.append("_Queue is empty._")

    blockers = []
    for entry in queued:
        match = re.search(r"cannot answer '([^']+)' - (.*)$", entry.get("reason") or "")
        if match:
            blockers.append((match.group(1), match.group(2), entry["company"]))
    if blockers:
        lines += [
            "",
            f"## Questions that blocked an application ({len(blockers)})",
            "",
            "Add a rule for any of these under `answer_rules:` in jobs.yaml and"
            " the next run gets past it.",
            "",
        ]
        seen = set()
        for question, why, company in blockers:
            if question in seen:
                continue
            seen.add(question)
            lines.append(f"- \"{question}\" ({company}) - {why}")

    if totals["outcomes"]:
        lines += ["", "## Apply outcomes", ""]
        for status, count in sorted(totals["outcomes"].items()):
            lines.append(f"- {status}: {count}")

    lines.append("")
    return "\n".join(lines)


def summarise(summary: dict) -> str:
    """Short console report printed at the end of a run."""
    totals = summary.get("day_totals") or {}
    verb = "would apply to" if summary["dry_run"] else "applied to"
    outcomes = ", ".join(f"{k}={v}" for k, v in sorted(summary["outcomes"].items())) or "none"
    return (
        f"\n  This run: scanned {summary['collected']} listings, "
        f"{summary['considered']} worth considering.\n"
        f"  {verb.capitalize()}: {len(summary['applied'])}\n"
        f"  Queued for review: {len(summary['queued'])}\n"
        f"  Outcomes: {outcomes}\n"
        f"\n  Today ({totals.get('runs', 1)} run(s)): "
        f"{totals.get('found', 0)} matches found, "
        f"{totals.get('applied', 0)} applied, "
        f"{totals.get('queued', 0)} awaiting review.\n"
        f"  Report: data/jobs/report-{date.today().isoformat()}.md\n"
    )
