"""Scheduled runs search LinkedIn and apply on it once a day; runs you start yourself are free.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import linkedin_daily  # noqa: E402


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr(linkedin_daily, "PATH", tmp_path / "linkedin_daily.json")
    monkeypatch.delenv(linkedin_daily.ENV, raising=False)
    return linkedin_daily


def test_a_run_you_start_is_never_held_back(gate):
    assert gate.take("search") and gate.take("search") and gate.take("apply")


def test_a_search_you_start_uses_up_the_schedules_turn(gate, monkeypatch):
    assert gate.take("search")
    monkeypatch.setenv(gate.ENV, "1")
    assert not gate.take("search")
    assert gate.take("apply")          # apply has its own turn


def test_scheduled_runs_get_one_search_and_one_apply_a_day(gate, monkeypatch):
    monkeypatch.setenv(gate.ENV, "1")
    assert gate.take("search")
    assert not gate.take("search")
    assert not gate.allowed("search")
    assert "already ran today" in gate.label("search")
    # the apply turn is separate from the search turn
    assert gate.take("apply")
    assert not gate.take("apply")


def test_yesterdays_turn_does_not_count_today(gate, monkeypatch):
    monkeypatch.setenv(gate.ENV, "1")
    yesterday = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    gate.PATH.write_text(json.dumps({"search": yesterday, "apply": yesterday}), encoding="utf-8")
    assert gate.label("search") == ""
    assert gate.take("search") and gate.take("apply")


def test_a_manual_run_after_the_scheduled_turn_still_goes(gate, monkeypatch):
    monkeypatch.setenv(gate.ENV, "1")
    assert gate.take("apply")
    monkeypatch.delenv(gate.ENV)
    assert gate.take("apply")


def test_a_broken_state_file_does_not_block(gate, monkeypatch):
    monkeypatch.setenv(gate.ENV, "1")
    gate.PATH.write_text("not json", encoding="utf-8")
    assert gate.take("search")
