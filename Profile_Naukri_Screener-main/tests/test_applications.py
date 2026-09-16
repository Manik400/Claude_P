"""The applications log: every attempt on record, every answer with its source.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import applications  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(applications, "LOG_PATH", tmp_path / "applications.jsonl")
    monkeypatch.setattr(applications, "PAGE_PATH", tmp_path / "applications.html")
    monkeypatch.setattr(applications, "JOBS_DIR", tmp_path)
    return tmp_path


def job(**kw):
    base = dict(job_id="150926933871", title="Backend Developer", company="Soul Ai",
                url="https://www.naukri.com/job-listings-x-150926933871", location="Remote", score=61.5)
    base.update(kw)
    return SimpleNamespace(**base)


def test_record_keeps_every_answer_with_its_source_and_fix_hint(store):
    capture = {"answers": [
        {"question": "What is your notice period?", "options": ["Immediate", "1 month", "2 months"],
         "answer": "2 months", "source": "from notice_period"},
        {"question": "How many years of experience in Python?", "options": [],
         "answer": "1", "source": "IT-skills table: python"},
        {"question": "Are you ok with 5 days office?", "options": ["Yes", "No"],
         "answer": "Yes", "source": "your rule '5 days office|work from office'"},
    ]}
    entry = applications.record("naukri", job(), "applied", "answered 3 question(s)", capture)

    assert entry["company"] == "Soul Ai" and entry["url"].startswith("https://")
    assert entry["at"][:4].isdigit() and entry["board"] == "naukri" and entry["status"] == "applied"
    fixes = [a["fix"] for a in entry["answers"]]
    assert "Naukri profile header" in fixes[0]
    assert "skill_years" in fixes[1]
    assert "answer_rules" in fixes[2]

    lines = applications.LOG_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["answers"][0]["answer"] == "2 months"


def test_a_blocked_question_is_recorded_with_the_reason(store):
    capture = {"question": "What is your expected CTC?", "options": [],
               "why": "'expected_ctc' is not on your profile - set answers.expected_ctc in jobs.yaml",
               "answers": [{"question": "Notice period?", "options": [], "answer": "2", "source": "from notice_period"}]}
    entry = applications.record("linkedin", job(job_id="linkedin:1"), "questionnaire",
                                "cannot answer 'What is your expected CTC?'", capture)
    assert entry["blocked"]["question"] == "What is your expected CTC?"
    assert len(entry["answers"]) == 1


def test_counts_ignore_dry_runs_and_split_by_board(store):
    applications.record("naukri", job(), "applied", "ok")
    applications.record("linkedin", job(job_id="linkedin:2"), "applied", "ok")
    applications.record("linkedin", job(job_id="linkedin:3"), "questionnaire", "blocked", {"question": "Q?"})
    applications.record("naukri", job(job_id="9"), "would-apply", "dry", dry_run=True)
    totals = applications.counts(applications.load())
    assert totals == {"attempts": 3, "applied": 2, "applied_today": 2, "naukri": 1, "linkedin": 1, "waiting": 1}


def test_page_is_built_from_the_log_and_a_bad_line_is_skipped(store):
    applications.record("naukri", job(), "applied", "ok",
                        {"answers": [{"question": "Q <b>", "options": [], "answer": "A", "source": "from notice_period"}]})
    with applications.LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    assert len(applications.load()) == 1
    page = applications.build_page().read_text(encoding="utf-8")
    assert "1 application sent" in page
    assert "Q \\u003cb>" in page  # the data block never carries a raw "<"
    assert "Applications sent" in page
