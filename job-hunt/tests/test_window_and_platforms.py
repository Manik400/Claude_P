"""The recency window, the platform picker and the title-first relevance gate.

The rule these tests exist to hold: a window measured in hours only keeps a
posting the board actually timed. A date is not a time, so "last 2 hours" can
never be satisfied by "posted today" - otherwise the list says two hours and
means yesterday.

Run from job-hunt/:  python -m pytest tests -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import job_bot  # noqa: E402
from jobbot.models import Job  # noqa: E402
from jobbot.search import _title_verdict, postfilter  # noqa: E402
from jobbot.sources.base import SearchContext  # noqa: E402
from jobbot.textutil import parse_when  # noqa: E402


def ctx(**kw):
    kw.setdefault("roles", ["software engineer", "software developer"])
    kw.setdefault("countries", ["DE"])
    return SearchContext(**kw)


def job(title="Backend Developer", **kw):
    base = dict(source="x", source_name="X", title=title, company="Acme", url="https://e.com/1", country="DE")
    base.update(kw)
    return Job(**base).finalize()


def ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


# --- reading a posting time -------------------------------------------------

def test_exact_times_are_read_dates_are_not_promoted_to_times():
    assert parse_when("2026-09-18T03:05:00Z")[1] is not None
    assert parse_when("45 minutes ago")[1] is not None
    assert parse_when("vor 3 Stunden")[1] is not None
    assert parse_when(1758150000)[1] is not None
    date, at = parse_when("2026-09-17")
    assert date == "2026-09-17" and at is None, "a date must not become midnight"


def test_relative_days_give_a_date_only():
    date, at = parse_when("2 days ago")
    assert date and at is None


# --- the window -------------------------------------------------------------

def test_hours_window_keeps_what_is_inside_it():
    ok, why = ctx(hours=2).fresh_job(job(posted_at=ago(minutes=30)))
    assert ok and why == ""


def test_hours_window_drops_what_is_outside_it():
    ok, why = ctx(hours=2).fresh_job(job(posted_at=ago(hours=5)))
    assert not ok and why == "old"


def test_under_a_day_a_posting_with_no_time_is_dropped():
    today = datetime.now(timezone.utc).date().isoformat()
    ok, why = ctx(hours=2).fresh_job(job(posted=today))
    assert not ok and why == "undated"


def test_allow_undated_keeps_those_postings():
    today = datetime.now(timezone.utc).date().isoformat()
    ok, _ = ctx(hours=2, allow_undated=True).fresh_job(job(posted=today))
    assert ok


def test_days_window_still_works_on_dates_alone():
    c = ctx(days=7)
    inside = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
    outside = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    assert c.fresh_job(job(posted=inside))[0]
    assert not c.fresh_job(job(posted=outside))[0]


def test_hours_wins_over_days_and_reaches_the_boards_as_seconds():
    c = ctx(days=30, hours=2)
    assert c.window_hours == 2 and c.recency_seconds == 7200
    assert ctx(days=7).recency_seconds == 7 * 24 * 3600
    assert ctx(days=0).recency_seconds is None


# --- platforms --------------------------------------------------------------

def test_platform_names_and_keys_both_resolve():
    picked, unknown = job_bot.parse_platforms("linkedin, The Muse, seek/jobsdb, apify-naukri")
    assert picked == ["linkedin", "themuse", "seek", "apify-naukri"]
    assert unknown == []


def test_unknown_platform_is_reported_not_silently_dropped():
    picked, unknown = job_bot.parse_platforms("linkedin, not-a-board")
    assert picked == ["linkedin"] and unknown == ["not-a-board"]


def test_no_platforms_asked_means_every_platform():
    assert job_bot.parse_platforms("") == ([], [])


# --- what counts as a match -------------------------------------------------

def test_the_title_decides_not_a_word_buried_in_the_description():
    c = ctx()
    assert _title_verdict(c, job("Software Engineer"), 0.4)[0]
    assert _title_verdict(c, job("Softwareentwickler (m/w/d)"), 0.4)[0]
    assert not _title_verdict(c, job("Sales Executive", description="we build software with engineers"), 0.4)[0]


def test_a_software_title_in_other_words_is_rescued_by_the_description():
    c = ctx()
    assert _title_verdict(c, job("Backend (m/w/d)", description="You will join our software engineering team"), 0.4)[0]
    assert _title_verdict(c, job("SDE-2, Java", description="backend developer role"), 0.4)[0]


def test_another_profession_is_dropped_even_when_the_advert_mentions_software():
    c = ctx()
    for title in ("Recruiter - Tech", "Marketing Manager", "Nurse"):
        assert not _title_verdict(c, job(title, description="software engineer team"), 0.4)[0], title


def test_postfilter_counts_each_reason_separately():
    c = ctx(hours=2)
    today = datetime.now(timezone.utc).date().isoformat()
    kept = postfilter(c, [
        job("Software Engineer", posted_at=ago(minutes=10)),        # kept
        job("Software Engineer", posted_at=ago(hours=9)),           # outside the window
        job("Software Engineer", posted=today),                     # no time on it
        job("Sales Executive", posted_at=ago(minutes=10)),          # other field
    ], log=lambda *a, **k: None)
    assert [j.title for j in kept] == ["Software Engineer"]
