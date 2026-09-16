"""The dashboard's data: your answers laid over jobs.yaml, and Gmail replies
matched to applications.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import answers, my_answers, responses  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(my_answers, "PATH", tmp_path / "my_answers.yaml")
    monkeypatch.setattr(responses, "STORE_PATH", tmp_path / "responses.json")
    monkeypatch.setattr(responses, "CONFIG_PATH", tmp_path / "gmail.yaml")
    return tmp_path


def test_saved_form_wins_over_jobs_yaml_and_policies_become_rules(store):
    my_answers.save({
        "facts": {"expected_ctc": "12", "phone": "9876543210", "notice_period_months": "1",
                  "current_location": "Gurugram", "total_experience_years": ""},
        "skill_years": {"NestJS": "1", "bad": "x"},
        "policies": {"bond": "no", "wfo": "yes", "shifts": "ask"},
    })
    config = {"answers": {"expected_ctc": "8 LPA", "willing_to_relocate": True},
              "skill_years": {"python": 1}, "answer_rules": [{"match": "shift", "answer": "Yes"}]}
    my_answers.overlay(config)

    assert config["answers"]["expected_ctc"] == "12"
    assert config["answers"]["phone"] == "9876543210"
    assert config["answers"]["willing_to_relocate"] is True          # untouched
    assert config["skill_years"] == {"python": 1, "NestJS": 1.0}     # "x" dropped
    assert config["fact_overrides"] == {"notice_period_months": 1.0, "current_location": "Gurugram"}

    facts = answers.build_facts({"notice_period": "3 Months", "location": "Pune, INDIA"}, config)
    assert facts["notice_period_months"] == 1.0
    assert facts["current_location"] == "Gurugram"
    assert facts["stated_phone"] == "9876543210"

    # Policies: No to a bond, Yes to office, and an explicit "ask me" on
    # shifts that beats the jobs.yaml rule which would have said Yes.
    assert answers.resolve("Are you ok to sign a 2 year bond?", ["Yes", "No"], facts)[0] == "No"
    assert answers.resolve("Comfortable with work from office 5 days?", ["Yes", "No"], facts)[0] == "Yes"
    answer, reason = answers.resolve("Are you ok with rotational shifts?", ["Yes", "No"], facts)
    assert answer is None and "keeps this one for you" in reason


def test_form_state_shows_saved_values_and_profile_fallbacks(store):
    my_answers.save({"facts": {"expected_ctc": "12"}, "skill_years": {}, "policies": {"bond": "no"}})
    state = my_answers.form_state({"notice_period": "2 Months notice period"},
                                  {"answers": {"phone": "111"}, "skill_years": {"sql": 3}, "profile_skills": ["SQL"]})
    assert state["facts"]["expected_ctc"]["value"] == "12"
    assert state["facts"]["phone"]["from_jobs_yaml"] == "111"
    assert state["facts"]["notice_period_months"]["from_profile"] == "2 Months notice period"
    assert state["skill_years"] == {"sql": 3}
    assert next(p for p in state["policies"] if p["id"] == "bond")["choice"] == "no"
    assert next(p for p in state["policies"] if p["id"] == "pay_cut")["choice"] == "no"   # default


def test_replies_are_classified_and_matched_by_company(store):
    apps = [
        {"job_id": "1", "status": "applied", "company": "Tripjack", "title": "SDE 1 (Java)"},
        {"job_id": "2", "status": "applied", "company": "Soul Ai", "title": "Backend Developer"},
        {"job_id": "3", "status": "questionnaire", "company": "Tripjack", "title": "SDE 2"},
    ]
    rejected = {"from": "careers@tripjack.com", "subject": "Your application to Tripjack",
                "body": "Unfortunately we will not be moving forward with your application for SDE 1."}
    assert responses.classify(rejected["subject"], rejected["body"]) == "rejected"
    assert responses.match_applications(rejected, apps) == ["1"]       # not the unapplied job 3

    interview = {"from": "hr@soulai.in", "subject": "Interview - Backend Developer at Soul Ai",
                 "body": "Please confirm your availability for a technical discussion."}
    assert responses.classify(interview["subject"], interview["body"]) == "interview"
    assert responses.match_applications(interview, apps) == ["2"]

    viewed = {"from": "LinkedIn <jobs-noreply@linkedin.com>", "subject": "Your application was viewed by Tripjack",
              "body": "Tripjack viewed your application for SDE 1 (Java)."}
    assert responses.classify(viewed["subject"], viewed["body"]) == "viewed"
    assert responses.match_applications(viewed, apps) == ["1"]

    noise = {"from": "newsletter@linkedin.com", "subject": "Jobs you may like", "body": "Backend Developer roles near you"}
    assert responses.match_applications(noise, apps) == []

    responses.save_store({"synced_at": "now", "emails": [
        dict(rejected, id="a", date="2026-09-16T10:00", kind="rejected", jobs=["1"], snippet=""),
        dict(viewed, id="b", date="2026-09-15T10:00", kind="viewed", jobs=["1"], snippet=""),
    ]})
    per = responses.per_application()
    assert per["1"]["kind"] == "rejected" and len(per["1"]["emails"]) == 2
    assert per["1"]["emails"][0]["kind"] == "rejected"                 # newest first


def test_gmail_config_roundtrip_and_missing(store):
    assert not responses.configured()
    with pytest.raises(responses.GmailNotConfigured):
        responses.load_config()
    responses.save_config("me@gmail.com", "abcd efgh ijkl mnop", 45)
    config = responses.load_config()
    assert config == {"email": "me@gmail.com", "app_password": "abcdefghijklmnop", "days": 45}
