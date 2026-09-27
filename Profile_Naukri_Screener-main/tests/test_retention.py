"""Reports older than 30 days are deleted; saved answers older than 3 months are asked again.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri import retention  # noqa: E402
from naukri.jobs import questions  # noqa: E402

TODAY = dt.date(2026, 11, 1)


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_only_dated_reports_older_than_30_days_go(tmp_path, monkeypatch):
    jobs, interview, hunt = tmp_path / "jobs", tmp_path / "interview", tmp_path / "JobHunt"
    monkeypatch.setattr(retention, "DATED", [(jobs, "openings-*.html"), (jobs, "results-*.json"),
                                             (interview, "interview-prep-*.html")])
    monkeypatch.setattr(retention, "STAMPED", [(jobs / "career_shots", "*.png")])
    monkeypatch.setattr(retention, "INTERVIEW", interview)
    old = [_touch(jobs / "openings-2026-09-26-r18.html"), _touch(jobs / "results-2026-09-20.json"),
           _touch(interview / "interview-prep-2026-09-20-r1.html"),
           _touch(jobs / "career_shots" / "20260926-1448-transverser.png")]
    old_run = hunt / "2026-09-11_0146_software-engineer"
    _touch(old_run / "report.html")
    fresh = [_touch(jobs / "openings-2026-10-15-r1.html"), _touch(jobs / "career_shots" / "20261020-0900-x.png")]
    fresh_run = hunt / "2026-10-20_1000_software-engineer"
    _touch(fresh_run / "report.html")
    # records the agent works from - never touched, whatever their age
    keep = [_touch(jobs / "ledger.json"), _touch(jobs / "applications.jsonl"), _touch(jobs / "answer_bank.yaml"),
            _touch(interview / "bank.json")]
    _touch(interview / "index.json", json.dumps({"2026-09-20-r1": {}, "2026-10-15-r1": {}}))
    _touch(hunt / "notes" / "keep.txt")          # not a dated run folder

    assert retention.prune(today=TODAY, jobhunt=hunt) == len(old) + 1
    assert not any(p.exists() for p in old) and not old_run.exists()
    assert all(p.exists() for p in fresh + keep) and fresh_run.exists() and (hunt / "notes").exists()
    assert list(json.loads((interview / "index.json").read_text(encoding="utf-8"))) == ["2026-10-15-r1"]


def _bank(tmp_path, monkeypatch, entries):
    monkeypatch.setattr(questions, "PENDING_PATH", tmp_path / "questions.yaml")
    monkeypatch.setattr(questions, "BANK_PATH", tmp_path / "answer_bank.yaml")
    questions.save_bank(entries)


def test_answers_older_than_3_months_are_asked_again(tmp_path, monkeypatch):
    _bank(tmp_path, monkeypatch, [
        {"question": "What is your current in-hand salary?", "answer": "68000 INR", "options": [],
         "answered_at": "2026-07-01T10:00:00"},
        {"question": "LinkedIn Profile", "answer": "https://linkedin.com/in/me", "options": [],
         "answered_at": "2026-10-01T10:00:00"},
        {"question": "Do you have a security clearance?", "answer": "skip", "options": [],
         "answered_at": "2026-01-01T10:00:00"},
    ])
    bank = questions.load_bank(today=TODAY)
    # the stale answer is no longer used; the fresh one and the old "skip" still are
    assert questions.lookup("What is your current in-hand salary?", bank) is None
    assert questions.lookup("LinkedIn Profile", bank)["answer"] == "https://linkedin.com/in/me"
    assert questions.lookup("Do you have a security clearance?", bank)["answer"] == "skip"

    assert questions.reask_stale(today=TODAY) == 1
    assert questions.reask_stale(today=TODAY) == 0           # asked once, not piled up
    waiting = questions.load_pending()
    assert [(w["question"], w["previous_answer"], w["answer"]) for w in waiting] == \
        [("What is your current in-hand salary?", "68000 INR", "")]

    # "keep" re-confirms the previous answer with today's date
    waiting[0]["answer"] = "keep"
    questions.save_pending(waiting)
    questions.absorb()
    entry = questions.load_bank()[questions.key("What is your current in-hand salary?")]
    assert entry["answer"] == "68000 INR" and entry["answered_at"][:10] == dt.date.today().isoformat()
    assert questions.load_pending() == []
