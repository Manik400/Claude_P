import json
import re
from datetime import date, timedelta
from pathlib import Path

PLAN = json.loads((Path(__file__).resolve().parent.parent / "plan.json").read_text(encoding="utf-8"))
DAYS = PLAN["days"]


def test_75_consecutive_days_from_a_monday():
    assert len(DAYS) == 75
    start = date.fromisoformat(PLAN["start"])
    assert start.weekday() == 0
    for i, d in enumerate(DAYS):
        assert d["day"] == i + 1
        assert d["date"] == (start + timedelta(days=i)).isoformat()


def test_weekend_days_land_on_weekends():
    for d in DAYS:
        if d["type"] == "Build Saturday":
            assert d["weekday"] == "Sat", d["day"]
        if d["type"] == "Review Sunday":
            assert d["weekday"] == "Sun", d["day"]


def test_three_unique_leetcode_a_day_with_links():
    names = [q["name"] for d in DAYS for q in d["leetcode"]]
    assert all(len(d["leetcode"]) == 3 for d in DAYS)
    assert len(names) == 225 == len(set(names))
    for d in DAYS:
        for q in d["leetcode"]:
            assert re.fullmatch(r"https://leetcode\.com/problems/[a-z0-9-]+/", q["url"]), q
            assert q["difficulty"] in ("Easy", "Medium", "Hard")


def test_every_day_is_complete():
    for d in DAYS:
        assert d["theme"] and d["dsa"]["pattern"] and d["dsa"]["tip"]
        assert d["hld"]["topic"] and len(d["hld"]["points"]) == 3
        assert d["lld"]["topic"] and d["cloud"]["topic"]
        assert d["cloud"]["provider"] == ("AWS" if d["day"] <= 50 else "Azure")


def test_checkpoints_on_25_50_75():
    assert [d["day"] for d in DAYS if d.get("checkpoint")] == [25, 50, 75]
