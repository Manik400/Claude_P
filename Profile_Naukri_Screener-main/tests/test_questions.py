"""The screening-question store: what waits for you, and what is remembered.

Run: python -m pytest tests/ -q

The store's one job is to make sure a question you answer once is answered
for every later job that asks it, and never stretched to a question you did
not answer. Both files live under data/jobs/, so every test points the module
at a temporary directory first.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import answers, questions  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(questions, "PENDING_PATH", tmp_path / "questions.yaml")
    monkeypatch.setattr(questions, "BANK_PATH", tmp_path / "answer_bank.yaml")
    return tmp_path


def job(job_id="1", title="Backend Developer", company="Acme", url="https://example.test/1"):
    return SimpleNamespace(job_id=job_id, title=title, company=company, url=url)


def test_key_ignores_case_punctuation_and_the_required_star():
    same = [
        "How many years of work experience do you have with Node.js?*",
        "how many years of work experience do you have with node.js",
        "  How many years of work experience do you have with Node.js ? (required)",
    ]
    assert len({questions.key(q) for q in same}) == 1


def test_key_keeps_skill_names_distinct():
    assert questions.key("years with C#") != questions.key("years with C")
    assert questions.key("years with Node.js") != questions.key("years with TypeScript")


def test_record_folds_a_repeat_question_into_one_entry(store):
    assert questions.record("What is your expected CTC?", [], job("1")) is True
    assert questions.record("what is your expected ctc", [], job("2", company="Beta")) is False
    pending = questions.load_pending()
    assert len(pending) == 1
    assert [j["job_id"] for j in pending[0]["jobs"]] == ["1", "2"]
    assert pending[0]["answer"] == ""
    assert questions.pending_count() == 1


def test_absorb_moves_answers_to_the_bank_and_frees_the_jobs(store):
    questions.record("What is your expected CTC?", [], job("1"))
    questions.record("Are you ok with a bond?", ["Yes", "No"], job("1"))
    questions.record("How many years with Node.js?", [], job("2"))

    pending = questions.load_pending()
    pending[0]["answer"] = "12 LPA"
    pending[2]["answer"] = "2"
    questions.save_pending(pending)

    absorbed, retry = questions.absorb()
    assert len(absorbed) == 2
    # Job 1 still has the bond question open, so only job 2 is free to retry.
    assert [j["job_id"] for j in retry] == ["2"]
    assert questions.pending_count() == 1

    bank = questions.load_bank()
    assert questions.lookup("What is your expected CTC?", bank)["answer"] == "12 LPA"
    assert questions.lookup("how many years with node.js?*", bank)["answer"] == "2"
    assert questions.lookup("Are you ok with a bond?", bank) is None


def test_skip_is_remembered_but_frees_no_job(store):
    questions.record("Are you ok with a bond?", ["Yes", "No"], job("1"))
    pending = questions.load_pending()
    pending[0]["answer"] = "skip"
    questions.save_pending(pending)
    absorbed, retry = questions.absorb()
    assert len(absorbed) == 1 and retry == []
    assert questions.lookup("Are you ok with a bond?", questions.load_bank())["answer"] == "skip"


def test_resolve_uses_the_bank_after_your_rules_and_before_guessing(store):
    facts = answers.build_facts({}, {"profile_skills": [], "answers": {}})
    facts["_bank"] = {
        questions.key("How many years with NestJS?"): {"question": "How many years with NestJS?", "answer": "1"},
        questions.key("Are you ok with a bond?"): {"question": "Are you ok with a bond?", "answer": "skip"},
    }
    assert answers.resolve("How many years with NestJS?", [], facts) == ("1", "your saved answer")
    answer, reason = answers.resolve("Are you ok with a bond?", ["Yes", "No"], facts)
    assert answer is None and "skip" in reason
    # A different question is never answered from a saved one.
    assert answers.resolve("How many years with Django?", [], facts)[0] is None


def test_a_broken_pending_file_is_moved_aside_not_overwritten(store):
    questions.PENDING_PATH.write_text("- question: [unclosed", encoding="utf-8")
    assert questions.load_pending() == []
    assert (store / "questions.broken.yaml").exists()


# ------------------------------------------------- LinkedIn's daily limit

def test_linkedin_limit_pause_is_24_hours(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from naukri.jobs import linkedin_limit

    monkeypatch.setattr(linkedin_limit, "PATH", tmp_path / "linkedin_limit.json")
    assert not linkedin_limit.active() and linkedin_limit.label() == ""
    end = linkedin_limit.hit()
    assert linkedin_limit.active()
    assert timedelta(hours=23, minutes=59) < end - datetime.now() <= timedelta(hours=24)
    assert "paused until" in linkedin_limit.label()
    linkedin_limit.clear()
    assert not linkedin_limit.active()


def test_linkedin_limit_message_is_recognised():
    from naukri.jobs.linkedin_apply import LIMIT_RE

    for text in ("You’ve reached the Easy Apply application limit for today",
                 "You have reached the daily limit. Try again tomorrow.",
                 "You can't apply to any more jobs today"):
        assert LIMIT_RE.search(text), text
    assert not LIMIT_RE.search("Application sent. Your application was submitted.")
