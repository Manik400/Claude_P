"""The day's three scans run once a day, only between 10:00 and 23:00.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scan3  # noqa: E402


def _run(monkeypatch, tmp_path, now, done=None, pages=(), force=False):
    """Run main() with the clock at `now`; returns the scan kinds it started."""
    monkeypatch.setattr(scan3, "STATE", tmp_path / "scan3_done.json")
    monkeypatch.setattr(scan3, "LOCK", tmp_path / "scan3.lock")
    monkeypatch.setattr(scan3, "page_kinds", lambda day: set(pages))
    monkeypatch.setattr(scan3, "wait_for_network", lambda limit_s=300: True)
    if done:
        scan3.save_state({"date": now.date().isoformat(), "done": {k: "x" for k in done}, "tries": {}})

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(scan3, "datetime", Clock)
    started = []

    def call(cmd, cwd=None):
        for kind, flags in scan3.SCANS:
            if "--jobs-export" in cmd and cmd[cmd.index("60") + 1:-2] == flags:
                started.append(kind)
        return 0
    monkeypatch.setattr(scan3.subprocess, "call", call)
    monkeypatch.setattr(sys, "argv", ["scan3.py"] + (["--force"] if force else []))
    scan3.main()
    return started


def test_nothing_runs_outside_10_to_23(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, datetime(2026, 9, 27, 9, 30)) == []
    assert _run(monkeypatch, tmp_path, datetime(2026, 9, 27, 23, 5)) == []


def test_first_check_of_the_day_runs_all_three_then_never_again(monkeypatch, tmp_path):
    now = datetime(2026, 9, 27, 13, 0)
    assert _run(monkeypatch, tmp_path, now) == ["Last 24h", "Early", "All jobs"]
    assert _run(monkeypatch, tmp_path, now.replace(hour=16)) == []


def test_only_the_missing_scan_runs(monkeypatch, tmp_path):
    now = datetime(2026, 9, 27, 13, 0)
    assert _run(monkeypatch, tmp_path, now, done=["Last 24h"], pages=["Early"]) == ["All jobs"]


def test_force_runs_all_three_whatever_the_time(monkeypatch, tmp_path):
    now = datetime(2026, 9, 27, 7, 0)
    assert _run(monkeypatch, tmp_path, now, done=["Last 24h", "Early", "All jobs"], force=True) == \
        ["Last 24h", "Early", "All jobs"]
