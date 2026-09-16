"""The job-hunt side of applying: which postings become LinkedIn cards, and
how outcomes are written back for the report.

Run from job-hunt/:  python -m pytest tests -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from jobbot import autoapply  # noqa: E402
from jobbot.models import Job  # noqa: E402


def job(url, **kw):
    base = dict(source="linkedin", source_name="LinkedIn", title="Backend Engineer", company="Acme",
                url=url, country="DE")
    base.update(kw)
    return Job(**base).finalize()


def test_only_linkedin_view_urls_become_cards_best_first():
    jobs = [
        job("https://www.linkedin.com/jobs/view/111/?trk=x", score=40),
        job("https://www.seek.com.au/job/222", source="seek", score=90),
        job("https://www.linkedin.com/jobs/view/333", score=80),
        job("https://www.linkedin.com/jobs/view/444", score=95, fit="no"),
        job("https://www.linkedin.com/jobs/view/555", score=None),
    ]
    cards = autoapply.linkedin_cards(jobs)
    assert [c["job_id"] for c in cards] == ["333", "111", "555"]
    assert cards[0]["url"] == "https://www.linkedin.com/jobs/view/333/"
    assert cards[0]["easy_apply"] is True
    assert [c["job_id"] for c in autoapply.linkedin_cards(jobs, min_score=50)] == ["333"]


def test_outcomes_are_written_into_extra_for_the_report():
    jobs = [job("https://www.linkedin.com/jobs/view/111"), job("https://www.linkedin.com/jobs/view/222")]
    marked = autoapply.mark_jobs(jobs, {
        "linkedin:111": {"status": "applied", "note": "LinkedIn confirmed the application"},
        "linkedin:999": {"status": "applied", "note": "not in this run"},
        "_summary": {},
    })
    assert marked == 1
    assert jobs[0].extra == {"applied_status": "applied", "applied_note": "LinkedIn confirmed the application"}
    assert jobs[1].extra == {}
    assert jobs[0].to_dict()["extra"]["applied_status"] == "applied"


def test_sibling_project_is_found_next_door():
    root = autoapply.sibling_dir()
    assert root and os.path.isfile(os.path.join(root, "main.py"))
