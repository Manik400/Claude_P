"""Apply to a run's LinkedIn results, using the Naukri screener's applier.

The worldwide search collects postings from twenty boards. Only one of them
can be applied to unattended from here: LinkedIn, whose Easy Apply dialog the
sibling project (Profile_Naukri_Screener-main) already drives, on a session
you signed in to once with `python main.py --linkedin-login` there. Every
other board (Seek, XING, Wellfound, JobsDB, TokyoDev ...) has its own login
and its own form, so those stay as Apply buttons on the report for you.

What this reuses from the sibling project, so there is ONE set of answers
and ONE record across both projects:

    naukri/jobs/linkedin_apply    the Easy Apply walker
    naukri/jobs/autoapply         pacing, per-run caps, the shared ledger, the
                                  applications log and the questions store
    naukri/jobs/answers + my_answers + questions
                                  the facts, dashboard form and answer bank
                                  used to answer screening questions

So a question LinkedIn asks here lands in the same data/jobs/questions.yaml,
the same dashboard answers it, and the same daily LinkedIn cap
(`linkedin_max_applies_per_day` in that project's jobs.yaml) bounds both
projects together - the ledger counts every LinkedIn application, whichever
search found the job.

    python scripts/job_bot.py apply --run <dir> [--limit N] [--yes]
    python scripts/job_bot.py run ... --apply-found --yes

Needs the sibling project's virtualenv (Playwright lives there):
jobhunt_apply.bat picks it automatically.
"""
from __future__ import annotations

import os
import re
import sys

SIBLING_NAMES = ("Profile_Naukri_Screener-main",)
LINKEDIN_VIEW = re.compile(r"linkedin\.com/jobs/view/(\d+)")


def sibling_dir() -> str | None:
    """The Naukri screener project: JOBHUNT_APPLIER_DIR, else a sibling folder."""
    env = os.environ.get("JOBHUNT_APPLIER_DIR")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for base in (os.path.dirname(here), here):
        for name in SIBLING_NAMES:
            candidate = os.path.join(base, name)
            if os.path.isfile(os.path.join(candidate, "main.py")):
                return candidate
    return None


class ApplierUnavailable(RuntimeError):
    """The sibling project or its browser stack cannot be loaded."""


def load_naukri():
    """Import the sibling project's modules. Raises ApplierUnavailable with
    the reason and the fix."""
    root = sibling_dir()
    if not root:
        raise ApplierUnavailable(
            "Cannot find the Profile_Naukri_Screener-main project next to job-hunt. "
            "Set JOBHUNT_APPLIER_DIR to its folder.")
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise ApplierUnavailable(
            "Playwright is not installed in this Python. Run the apply with the sibling "
            f"project's virtualenv: {os.path.join(root, '.venv', 'Scripts', 'python.exe')} "
            "(jobhunt_apply.bat does this for you).")
    from naukri.jobs import applications, autoapply, config as config_mod, linkedin  # noqa: E402
    return {"root": root, "applications": applications, "autoapply": autoapply,
            "config": config_mod, "linkedin": linkedin}


def linkedin_id(url: str) -> str | None:
    match = LINKEDIN_VIEW.search(url or "")
    return match.group(1) if match else None


def linkedin_cards(jobs, min_score: float | None = None) -> list[dict]:
    """The run's LinkedIn postings as cards the applier understands, best first.

    Postings the fit filter called "no" (too senior) are left out; there is no
    point spending a cap slot on a role that wants ten years.
    """
    cards = []
    for job in jobs:
        job_id = linkedin_id(getattr(job, "url", ""))
        if not job_id:
            continue
        if getattr(job, "fit", "") == "no":
            continue
        score = getattr(job, "score", None)
        if min_score is not None and (score is None or score < min_score):
            continue
        cards.append({
            "job_id": job_id,
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
            "title": getattr(job, "title", "") or "",
            "company": getattr(job, "company", "") or "",
            "location": getattr(job, "location", "") or "",
            "easy_apply": True,   # unknown from the guest search; the applier finds out on the page
            "_score": score or 0,
            "_run_id": getattr(job, "id", ""),
        })
    cards.sort(key=lambda c: -(c["_score"] or 0))
    return cards


def apply_run(jobs, per_run: int | None = None, dry_run: bool = True,
              min_score: float | None = None, headless: bool = True) -> dict:
    """Apply to the run's LinkedIn postings. Returns the applier's outcomes,
    keyed "linkedin:<id>", plus "_summary"."""
    mods = load_naukri()
    config_mod, autoapply = mods["config"], mods["autoapply"]
    profile = config_mod.load_profile()
    config = config_mod.load(profile=profile)
    cards = linkedin_cards(jobs, min_score=min_score)
    if not cards:
        return {"_summary": {"dry_run": dry_run, "naukri": {}, "linkedin": {}, "per_run": per_run,
                             "questions_saved": 0, "retried": 0, "pending_questions": 0,
                             "backlog": 0, "note": "no LinkedIn postings in this run"}}
    return autoapply.run([], cards, config, profile, headless=headless, dry_run=dry_run,
                         per_run=per_run, include_backlog=False, project="jobhunt")


def mark_jobs(jobs, outcomes: dict) -> int:
    """Write each outcome into the job's `extra`, so the report can show it."""
    marked = 0
    for job in jobs:
        job_id = linkedin_id(getattr(job, "url", ""))
        hit = outcomes.get(f"linkedin:{job_id}") if job_id else None
        if not hit:
            continue
        extra = getattr(job, "extra", None)
        if extra is None:
            job.extra = extra = {}
        extra["applied_status"] = hit.get("status", "")
        extra["applied_note"] = hit.get("note", "")
        marked += 1
    return marked


def summarise(outcomes: dict) -> str:
    try:
        return load_naukri()["autoapply"].summarise(outcomes)
    except ApplierUnavailable:
        return ""
