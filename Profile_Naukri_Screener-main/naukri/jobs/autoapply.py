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

import hashlib
import json
import logging
import os
import random
import time
from datetime import date, timedelta
from pathlib import Path

from . import answers as answers_mod
from . import career_apply as career_mod
from . import applications, applier, config as config_mod, linkedin as linkedin_mod, linkedin_apply, linkedin_limit, questions
from .ledger import Ledger
from .model import Job

log = logging.getLogger("naukri.jobs.autoapply")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"

# Seconds between two applications. Long and uneven on purpose - see PACE.
NAUKRI_PAUSE = (35.0, 80.0)
LINKEDIN_PAUSE = (50.0, 110.0)
# After a posting where nothing was submitted (no Easy Apply button, offsite,
# already applied) a long pause only burns the run: a run of 198 such postings
# took five hours and outlived its scheduled task.
SHORT_PAUSE = (6.0, 14.0)
NOTHING_SENT = {"offsite", "no-button", "already", "would-apply", "limit-reached", "limit-cooldown",
                "login-required", "captcha", "no-form", "career-error", "career-incomplete"}
# A run stops starting new applications after this many minutes
# (APPLY_MAX_MINUTES overrides; 0 = no limit) so it always ends before the
# scheduler's time limit and never leaves a browser running behind it.
DEFAULT_MAX_MINUTES = 40

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


def _deadline() -> float | None:
    """time.monotonic() after which no new application starts, or None."""
    raw = os.environ.get("APPLY_MAX_MINUTES", "").strip()
    minutes = float(raw) if raw.replace(".", "", 1).isdigit() else DEFAULT_MAX_MINUTES
    return time.monotonic() + minutes * 60 if minutes > 0 else None


def _out_of_time(deadline: float | None, board: str, left: int) -> bool:
    if deadline is None or time.monotonic() < deadline:
        return False
    log.info("%s: run time limit reached; %d job(s) left for the next run", board, left)
    return True


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
    elif status in ("would-apply", "limit-reached", "limit-cooldown"):
        return              # nothing happened to this job; it stays as it was
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


def _press(page, candidates) -> bool:
    """Click the first visible element among `candidates` (selectors)."""
    for selector in candidates:
        try:
            el = page.locator(selector).first
            if el.count() and el.is_visible(timeout=2500):
                el.click(timeout=8000)
                return True
        except Exception:
            continue
    return False


def run(kept: list, cards: list[dict], config: dict, profile: dict,
        headless: bool = False, dry_run: bool = True,
        per_run: int | None = None, include_backlog: bool = True,
        project: str = "naukri", web_jobs: list[dict] | None = None) -> dict:
    """Apply across both boards. Returns {row_id: {status, note}} plus
    a "_summary" entry with the counts.

    `kept` are the scan's Naukri Job objects (scored), `cards` its LinkedIn
    cards. Row ids match the tracker page: "naukri:<id>" / "linkedin:<id>".
    `per_run` caps applications per board for this run (None = only the
    daily caps apply). `include_backlog` adds the last two days' unsettled
    listings after this scan's own, so small runs drain the list over time.
    `project` tags the applications log with which search found the jobs.

    Postings that apply on the company's own site (Naukri "Apply on company
    site", LinkedIn's plain Apply) and `web_jobs` ({url, title, company,
    score, job_id?} from other boards) go to career_apply: skipped when the
    site wants a login or shows a CAPTCHA, otherwise filled and submitted.
    `career_apply: false` in jobs.yaml turns that off; at most `per_run`
    (else `career_max_per_run`, 5) company-site submissions per run.
    """
    from playwright.sync_api import sync_playwright

    from .. import selectors as S
    from ..session import DEFAULT_STATE, launch_browser, new_context, open_profile
    from . import simplify

    deadline = _deadline()
    facts = answers_mod.build_facts(profile, config)
    facts["_bank"] = questions.load_bank()
    phone = str(facts.get("stated_phone") or "").strip() or None
    ledger = Ledger()
    outcomes: dict[str, dict] = {}
    summary = {"dry_run": dry_run, "naukri": {}, "linkedin": {}, "career": {}, "questions_saved": 0,
               "retried": 0, "pending_questions": 0, "per_run": per_run, "backlog": 0}

    # ---------------------------------------------------------- company sites
    career_on = bool(config.get("career_apply", True))
    who = career_mod.applicant(profile, config) if career_on else {}
    if career_on and career_mod.missing_details(who):
        log.warning("Company-site applies off: missing %s (set applicant: in jobs.yaml)",
                    ", ".join(career_mod.missing_details(who)))
        career_on = False
    career_today = sum(1 for e in ledger.entries.values()
                       if e.get("status") == "applied" and str(e.get("note", "")).startswith(career_mod.TRIED)
                       and str(e.get("at", "")).startswith(date.today().isoformat()))
    career_left = [min(per_run if per_run is not None else int(config.get("career_max_per_run") or 5),
                       max(0, int(config.get("career_max_per_day") or 25) - career_today))]
    if career_on and career_left[0] <= 0:
        log.info("Company sites: today's cap of %s submissions is reached",
                 config.get("career_max_per_day") or 25)
    # `simplify: true` in jobs.yaml: every browser below is the one with
    # Simplify Copilot loaded, and each company form gets its autofill before
    # fill_form answers the rest (see simplify.py).
    use_simplify = career_on and simplify.wanted(config)
    if use_simplify and not simplify.ready():
        log.warning("Simplify is on in jobs.yaml but not set up (%s) - filling forms without it",
                    simplify.why_not_ready())
        use_simplify = False
    if use_simplify:
        log.info("Company-site forms go through Simplify Copilot (%s)", simplify.PROFILE_DIR)
    prefill = simplify.autofill if use_simplify else None

    def career_ready() -> bool:
        return career_on and career_left[0] > 0 and not (deadline and time.monotonic() >= deadline)

    def career_untried(job_id: str) -> bool:
        entry = ledger.entries.get(job_id) or {}
        return entry.get("status") == "offsite" and not str(entry.get("note", "")).startswith(career_mod.TRIED)

    # company-site forms get a resume tailored to the job (naukri/jobs/tailor.py); tailor_resume: false turns it off
    tailor_fn = None
    if config.get("tailor_resume", True):
        from . import tailor as tailor_mod
        tailor_fn = tailor_mod.tailor

    def try_career(page, job, board: str, offsite_click=None) -> tuple[str, str]:
        capture: dict = {}
        status, note = career_mod.apply_from_page(
            page, {"title": job.title, "company": job.company, "url": job.url,
                   "description": getattr(job, "description", "") or ""}, who, facts,
            dry_run=dry_run, capture=capture, offsite_click=offsite_click, prefill=prefill, tailor=tailor_fn)
        if status == "submitted":
            career_left[0] -= 1
        if not dry_run and status != "would-apply" and not career_mod.transient(status, note):
            ledger.record(job, career_mod.ledger_status(status), career_mod.TRIED + note)
            applications.record(board, job, {"submitted": "applied", "closed": "skipped"}.get(status, "offsite"),
                                career_mod.TRIED + note, capture, dry_run=False, per_run=per_run, project=project)
        summary["career"][status] = summary["career"].get(status, 0) + 1
        log.info("[company site %s] %s @ %s - %s", status, job.title, job.company, note)
        return status, note

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
    from naukri import learning
    # Score first, weighted by the learned chance this job's apply route works
    # (one-click / questionnaire / company site) - see naukri/learning.py.
    for job in sorted(kept, key=lambda j: (getattr(j, "score", 0) or 0) * learning.job_priority(j),
                      reverse=True):
        status = ledger.status(job.job_id)
        if (status in DONE or status == WAITING) and not (career_on and career_untried(job.job_id)):
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
            if use_simplify:
                browser, _ctx, page = simplify.open_naukri(p, headless=headless)
            else:
                browser, _ctx, page = open_profile(p, DEFAULT_STATE, headless=headless)
            try:
                for n, job in enumerate(naukri_jobs):
                    if budget <= 0 or _out_of_time(deadline, "Naukri", len(naukri_jobs) - n):
                        break
                    if career_untried(job.job_id) and not career_ready():
                        continue            # already settled as offsite; nothing new to do this run
                    capture: dict = {}
                    naukri_offsite = lambda: _press(page, S.JOB_APPLY_BUTTON)  # noqa: E731
                    if getattr(job, "company_apply", False) or career_untried(job.job_id):
                        if career_ready():
                            try:
                                page.goto(job.url, wait_until="domcontentloaded", timeout=60000)
                                page.wait_for_timeout(random.uniform(2200, 4200))
                                status, note = try_career(page, job, "naukri", naukri_offsite)
                            except Exception as exc:
                                status, note = "offsite", f"company site not reached: {str(exc)[:100]}"
                        else:
                            status, note = "offsite", "applies on the company's own site"
                    else:
                        status, note = applier.apply_to(page, job, dry_run=dry_run,
                                                        facts=facts, capture=capture)
                        _record(ledger, job, status, note, "naukri", capture)
                        if status == "questionnaire" and capture.get("question"):
                            summary["questions_saved"] += 1
                        if status == "offsite" and career_ready():
                            status, note = try_career(page, job, "naukri", naukri_offsite)
                    if status == "offsite" and not dry_run:
                        ledger.record(job, "offsite", note)
                    if not dry_run and status not in career_mod.STATUSES:
                        applications.record("naukri", job, status, note, capture,
                                            dry_run=False, per_run=per_run, project=project)
                    counts[status] = counts.get(status, 0) + 1
                    outcomes[f"naukri:{job.job_id}"] = {"status": status, "note": note}
                    log.info("[naukri %s] %s @ %s - %s", status, job.title, job.company, note)
                    if status in ("applied", "would-apply"):
                        budget -= 1
                    if not dry_run and budget > 0 and not getattr(job, "company_apply", False):
                        time.sleep(random.uniform(*(SHORT_PAUSE if status in NOTHING_SENT else NAUKRI_PAUSE)))
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
            # Plain-Apply postings are worth opening too when the career
            # applier is on: apply_to() reports them "offsite" and try_career
            # follows the button to the company's form.
            if not card.get("url") or not (card.get("easy_apply") or career_on):
                continue
            job = _card_job(card)
            if job.job_id in seen_ids:
                continue
            status = ledger.status(job.job_id)
            if status in DONE and not (career_on and career_untried(job.job_id)):
                continue
            if status == WAITING and job.job_id not in {c["job_id"] for c in retry_cards}:
                continue
            seen_ids.add(job.job_id)
            li_cards.append((card, job))
        # Easy Apply stops for the day when our own cap is spent or LinkedIn
        # said its limit is reached (linkedin_limit.py, 24 h). The postings
        # are still opened when the career applier can use them: a plain
        # Apply leads to the company's site, which no limit touches.
        paused = [linkedin_limit.active()]
        if li_cards and li_budget <= 0:
            log.info("LinkedIn: daily cap of %s already reached; %d job(s) left for tomorrow",
                     config.get("linkedin_max_applies_per_day"), len(li_cards))
            paused[0] = True
        if li_cards and linkedin_limit.active():
            log.info("LinkedIn: %s - Easy Apply postings are left alone; plain-Apply ones still go to the company site",
                     linkedin_limit.label())
        if li_cards and paused[0] and not career_ready():
            li_cards = []           # nothing this run could do with them
        if li_cards:
            log.info("LinkedIn: %s up to %d of %d job(s)%s",
                     "company-site applies from" if paused[0] else "Easy Apply to",
                     li_budget if not paused[0] else len(li_cards), len(li_cards),
                     " (dry run)" if dry_run else "")
            try:
                with sync_playwright() as p:
                    if use_simplify:
                        browser, _ctx, page = simplify.open_linkedin(p, headless=headless)
                    else:
                        browser, _ctx, page = linkedin_mod.open_session(p, headless=headless)
                    try:
                        for n, (card, job) in enumerate(li_cards):
                            if (li_budget <= 0 and not paused[0]) or _out_of_time(deadline, "LinkedIn", len(li_cards) - n):
                                break
                            if paused[0] and not career_ready():
                                break
                            if career_untried(job.job_id) and not career_ready():
                                continue
                            capture = {}
                            status, note = linkedin_apply.apply_to(
                                page, card, facts, dry_run=dry_run, phone=phone, capture=capture,
                                easy_apply_paused=paused[0])
                            if status == "limit-reached":
                                end = linkedin_limit.hit()
                                paused[0] = True
                                log.warning("LinkedIn: daily Easy Apply limit reached - Easy Apply paused until %s; "
                                            "Naukri, other boards, company sites and LinkedIn's plain-Apply postings continue",
                                            end.strftime("%Y-%m-%d %H:%M"))
                            if status == "offsite" and career_ready():
                                status, note = try_career(
                                    page, job, "linkedin",
                                    lambda: _press(page, [linkedin_apply.ANY_APPLY_BUTTON]))
                            else:
                                _record(ledger, job, status, note, "linkedin", capture)
                            if status == "questionnaire" and capture.get("question"):
                                summary["questions_saved"] += 1
                            if not dry_run and status not in career_mod.STATUSES                                     and status not in ("limit-reached", "limit-cooldown"):
                                applications.record("linkedin", job, status, note, capture,
                                                    dry_run=False, per_run=per_run, project=project)
                            counts[status] = counts.get(status, 0) + 1
                            outcomes[job.job_id] = {"status": status, "note": note}
                            log.info("[linkedin %s] %s @ %s - %s", status, job.title, job.company, note)
                            if status in ("applied", "would-apply"):
                                li_budget -= 1
                            if not dry_run and li_budget > 0:
                                time.sleep(random.uniform(*(SHORT_PAUSE if status in NOTHING_SENT else LINKEDIN_PAUSE)))
                    finally:
                        browser.close()
            except linkedin_mod.NotLoggedIn as exc:
                log.warning("LinkedIn applies skipped: %s", exc)
                counts["skipped-not-logged-in"] = len(li_cards)
            if not dry_run:
                ledger.save()

    # ------------------------------------------- other boards' / career pages
    web = []
    for item in web_jobs or []:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        job_id = item.get("job_id") or "web:" + hashlib.sha1(url.split("#")[0].lower().encode("utf-8")).hexdigest()[:16]
        if ledger.status(job_id) and not item.get("retry"):
            continue
        job = Job(job_id=job_id, title=item.get("title") or "", company=item.get("company") or "", url=url, source="web")
        job.score = item.get("score") or 0
        web.append(job)
    web.sort(key=lambda j: -(j.score or 0))
    if web and career_ready():
        log.info("Company sites: up to %d submission(s) from %d posting(s)%s", career_left[0], len(web),
                 " (dry run)" if dry_run else "")
        with sync_playwright() as p:
            if use_simplify:
                browser = simplify.launch(p, headless=headless, states=[DEFAULT_STATE, linkedin_mod.STATE_PATH])
                context = browser.context
            else:
                browser = launch_browser(p, headless=headless, offscreen=not headless)
                context = new_context(browser, viewport={"width": 1366, "height": 900})
            try:
                for n, job in enumerate(web):
                    if not career_ready():
                        _out_of_time(deadline, "Company sites", len(web) - n)
                        break
                    if any(h in job.url for h in career_mod.LOGIN_HOSTS):
                        status, note = "login-required", "this board needs its own account"
                        summary["career"][status] = summary["career"].get(status, 0) + 1
                        log.info("[company site %s] %s @ %s - %s", status, job.title, job.company, note)
                        if not dry_run:
                            ledger.record(job, "offsite", career_mod.TRIED + note)
                    else:
                        page = context.new_page()
                        try:
                            page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
                            page.wait_for_timeout(random.uniform(2500, 4000))
                            status, note = try_career(page, job, "web")
                        except Exception as exc:
                            status, note = "career-error", f"page did not open: {str(exc)[:100]}"
                            if not dry_run and not career_mod.transient(status, note):
                                ledger.record(job, "offsite", career_mod.TRIED + note)
                        finally:
                            try:
                                page.close()
                            except Exception:
                                pass
                    outcomes[job.job_id] = {"status": status, "note": note}
                    if status == "submitted" and not dry_run:
                        time.sleep(random.uniform(*SHORT_PAUSE))
            finally:
                browser.close()
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
    career = dict(summary.get("career") or {})
    if career:
        career["applied"] = career.pop("submitted", 0)
        lines.append(line("Company sites", career))
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
