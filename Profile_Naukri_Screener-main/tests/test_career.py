"""The company-site form filler's small decisions: dates, overlays, what is not the form,
and the answers it learns from forms that went through.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import career_apply, questions  # noqa: E402


def test_dates_become_what_a_date_box_takes():
    assert career_apply._iso_date("23 / 09 / 2003") == "2003-09-23"
    assert career_apply._iso_date("23 Sep 2003") == "2003-09-23"
    assert career_apply._iso_date("2003-09-23") == "2003-09-23"
    assert career_apply._iso_date("sometime") is None


def test_cookie_banners_are_declined_never_accepted():
    for text in ("Reject all", "Reject All Cookies", "DECLINE ALL", "Only necessary cookies", "Use necessary cookies only"):
        assert career_apply.COOKIE_DECLINE.match(text), text
    for text in ("Accept all cookies", "Accept", "Allow all"):
        assert not career_apply.COOKIE_DECLINE.match(text), text


def test_job_alert_and_search_boxes_are_not_the_form():
    field = {"name": "", "id": "", "placeholder": "your email", "ctx": "DIV alert Get similar jobs by email - create alert",
             "ctxFields": 1}
    assert career_apply._not_the_form(field)
    assert career_apply._not_the_form(dict(field, ctx="", ctxFields=99, name="keyword"))
    # a whole-page form is not judged by the words somewhere in it
    assert not career_apply._not_the_form(dict(field, ctxFields=12))


def test_learned_answers_are_short_and_never_duplicated(tmp_path, monkeypatch):
    monkeypatch.setattr(questions, "BANK_PATH", tmp_path / "answer_bank.yaml")
    questions.save_bank([{"question": "Graduation year", "answer": "2025"}])
    added = questions.learn([
        {"question": "Graduation year", "answer": "2024", "source": "local-ai: resume"},
        {"question": "Which city do you prefer?", "answer": "Gurgaon", "source": "local-ai: current_location"},
        {"question": "Why us?", "answer": "x" * 200, "source": "local-ai: long"},
    ])
    assert added == 1
    bank = questions.load_bank()
    assert bank[questions.key("Graduation year")]["answer"] == "2025"      # yours is never overwritten
    assert bank[questions.key("Which city do you prefer?")]["learned"].startswith("local-ai")


def test_an_answered_question_frees_its_job_even_cut_short(tmp_path, monkeypatch):
    monkeypatch.setattr(questions, "BANK_PATH", tmp_path / "answer_bank.yaml")
    monkeypatch.setattr(questions, "PENDING_PATH", tmp_path / "questions.yaml")
    long_q = "One product or piece of software you think is exceptionally well built and one sentence on why?"
    questions.save_bank([{"question": long_q, "answer": "Postgres - boring and correct."}])
    assert questions.answered(long_q[:60])
    assert not questions.answered("Something you shipped end to end that you're proud of?")


def test_jobs_parked_on_answered_questions_come_back(tmp_path):
    from datetime import date
    from naukri.jobs import autoapply
    from naukri.jobs.ledger import Ledger

    ledger = Ledger(tmp_path / "ledger.json")
    today = date.today().isoformat()
    ledger.entries = {
        "linkedin:1": {"status": "questionnaire-pending", "url": "https://www.linkedin.com/jobs/view/1/", "at": today,
                       "title": "A", "company": "X", "note": "cannot answer 'DOB (Date of Birth)' - no rule matches this question"},
        "linkedin:2": {"status": "questionnaire-pending", "url": "https://www.linkedin.com/jobs/view/2/", "at": today,
                       "title": "B", "company": "Y", "note": "cannot answer 'Yes No' - no rule matches this question"},
        "3": {"status": "questionnaire-pending", "url": "https://www.naukri.com/job-listings-3", "at": today,
              "title": "C", "company": "Z", "note": "cannot answer 'Middle name' - no rule matches this question"},
        "4": {"status": "applied", "url": "https://www.naukri.com/job-listings-4", "at": today, "note": ""},
    }
    jobs, cards = autoapply.unblocked_waiting(ledger, lambda q: "birth" in q.lower())
    assert sorted(c["job_id"] for c in cards) == ["linkedin:1", "linkedin:2"]
    assert jobs == []          # "Middle name" is still unanswered
