"""The salary floor and the honest window.

Two rules these tests hold:
  * a posting that STATES a salary below the floor goes; one that states none stays, marked -
    nobody knows what it pays, and "below ten lakh" is a claim the report must not invent;
  * a posting the board never timed is not thrown out on that alone any more: its own page is
    read for a date, and only one shown to be older than the window is dropped (strict mode
    drops the still-undated ones, which was the old default).

Run from job-hunt/:  python -m pytest tests -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import job_bot  # noqa: E402
from jobbot import dates, salary  # noqa: E402
from jobbot.models import Job  # noqa: E402
from jobbot.search import postfilter, salary_filter  # noqa: E402
from jobbot.sources.base import SearchContext  # noqa: E402

LAKH = 100_000


def ctx(**kw):
    kw.setdefault("roles", ["software engineer"])
    kw.setdefault("countries", ["IN"])
    return SearchContext(**kw)


def job(title="Software Engineer", **kw):
    base = dict(source="x", source_name="X", title=title, company="Acme", url="https://e.com/" + str(abs(hash(str(kw))) % 10**6), country="IN")
    base.update(kw)
    return Job(**base).finalize()


def ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


# --- reading pay ------------------------------------------------------------

def test_indian_formats_read_in_rupees_a_year():
    assert salary.parse("4-6 LPA").top_inr == 6 * LAKH
    assert salary.parse("₹4,00,000 - 6,00,000 P.A.").top_inr == 6 * LAKH
    assert salary.parse("CTC: 8 - 12 LPA").min_inr == 8 * LAKH
    assert salary.parse("6.5 lacs per annum").top_inr == 650_000
    s = salary.parse("Rs. 40,000 /month")
    assert s.period == "month" and s.top_inr == 480_000


def test_foreign_currencies_convert_and_small_figures_are_hourly():
    assert salary.parse("$120k–$150k").currency == "USD"
    assert salary.parse("$120k–$150k").top_inr > 100 * LAKH
    assert salary.parse("€60.000 – €75.000").min_inr == round(60_000 * salary.RATES_TO_INR["EUR"])
    assert salary.parse("$25 - $35 /hr").period == "hour"
    assert salary.parse("AED 15,000 per month").period == "month"


def test_numbers_about_time_or_people_are_not_money():
    for text in ("0-2 years", "5+ years experience", "2025 batch", "200 engineers", "40 hours per week", "Not disclosed"):
        assert salary.parse(text) is None, text


def test_find_in_text_skips_the_experience_range_and_reads_the_ctc():
    s = salary.find_in_text("We are hiring freshers (0-2 years). CTC: 4.5 - 6 LPA. Founded in 2015 with 500 employees.")
    assert s is not None and s.top_inr == 6 * LAKH
    assert salary.find_in_text("Experience: 2 - 4 years. Salary: Not Disclosed. Posted 3 days ago") is None


def test_a_typed_floor_means_lakhs_unless_it_says_otherwise():
    assert salary.parse_floor("10") == 10 * LAKH
    assert salary.parse_floor("10 LPA") == 10 * LAKH
    assert salary.parse_floor("12 lakh") == 12 * LAKH
    assert salary.parse_floor("1000000") == 10 * LAKH
    assert salary.parse_floor("") is None and salary.parse_floor("0") is None
    assert salary.label(10 * LAKH) == "10 LPA" and salary.label(750_000) == "7.5 LPA"


def test_salary_filter_drops_only_what_is_stated_below_the_floor():
    c = ctx(min_salary_inr=10 * LAKH)
    low = job("Software Engineer", salary="4-6 LPA")
    high = job("Software Engineer", description="Compensation: 12 - 18 LPA plus bonus")
    unknown = job("Software Engineer", description="Great team, free lunch")
    kept, dropped = salary_filter(c, [low, high, unknown], log=lambda *a, **k: None)
    assert dropped == 1 and [j for j in kept] == [high, unknown]
    assert high.extra["salary_stated"] is True and high.extra["salary_lpa"] == 18.0
    assert unknown.extra["salary_stated"] is False
    assert high.salary.startswith("Compensation")   # the phrase is kept so the phone can show it


def test_job_bot_reads_the_floor_from_the_flag():
    class A:
        min_salary = "10 LPA"
    assert job_bot.salary_floor(A()) == 10 * LAKH
    A.min_salary = ""
    assert job_bot.salary_floor(A()) is None


# --- the window, made honest ----------------------------------------------

def test_undated_postings_are_kept_by_default_and_dropped_only_in_strict_mode():
    today = datetime.now(timezone.utc).date().isoformat()
    ok, why = ctx(hours=2).fresh_job(job(posted=today))
    assert ok and why == ""
    ok, why = ctx(hours=2, strict_undated=True).fresh_job(job(posted=today))
    assert not ok and why == "undated"
    assert ctx(hours=2, allow_undated=False).fresh_job(job(posted=today))[0] is False


def test_from_html_reads_json_ld_meta_and_visible_text():
    html = '<html><head><script type="application/ld+json">{"@type":"JobPosting","datePosted":"2026-10-06T08:15:00Z"}</script></head></html>'
    d, at, how = dates.from_html(html)
    assert d == "2026-10-06" and at and at.startswith("2026-10-06T08:15") and how == "json-ld"
    d, at, how = dates.from_html('<meta property="article:published_time" content="2026-10-05">')
    assert d == "2026-10-05" and at is None and how == "meta"
    d, at, how = dates.from_html("<div>Senior role. Posted 3 days ago. Apply now</div>")
    assert d and at is None and how == "text"
    assert dates.from_html("<p>nothing about dates here</p>") == (None, None, "")


def test_verify_reads_pages_and_drops_only_what_is_shown_to_be_old():
    c = ctx(hours=2)
    old = job("Software Engineer", url="https://e.com/old")
    fresh = job("Software Engineer", url="https://e.com/fresh")
    silent = job("Software Engineer", url="https://e.com/silent")
    timed = job("Software Engineer", url="https://e.com/timed", posted_at=ago(minutes=10))
    pages = {
        "https://e.com/old": '<script type="application/ld+json">{"@type":"JobPosting","datePosted":"%s"}</script>' % ago(hours=9),
        "https://e.com/fresh": '<script type="application/ld+json">{"@type":"JobPosting","datePosted":"%s"}</script>' % ago(minutes=30),
        "https://e.com/silent": "<p>no date on this page</p>",
    }
    kept, dropped, checked = dates.verify(c, [old, fresh, silent, timed], fetch_html=lambda j: pages.get(j.url), log=lambda *a, **k: None)
    assert checked == 3 and dropped == 1
    assert [j.url for j in kept] == ["https://e.com/fresh", "https://e.com/silent", "https://e.com/timed"]
    assert fresh.posted_at and fresh.extra["posted_source"] == "page:json-ld"
    assert silent.extra["posted_checked"] == "none"
    # strict: the page said nothing, so the posting cannot be shown to be inside two hours
    kept, dropped, _ = dates.verify(ctx(hours=2, strict_undated=True), [silent], fetch_html=lambda j: pages.get(j.url), log=lambda *a, **k: None)
    assert kept == [] and dropped == 1


def test_a_days_window_only_checks_postings_with_no_date_at_all():
    c = ctx(days=7)
    dated = job("Software Engineer", posted=datetime.now(timezone.utc).date().isoformat())
    undated = job("Software Engineer", url="https://e.com/u")
    calls = []
    dates.verify(c, [dated, undated], fetch_html=lambda j: calls.append(j.url) or "<p></p>", log=lambda *a, **k: None)
    assert calls == ["https://e.com/u"]


def test_postfilter_keeps_the_undated_posting_for_the_page_check():
    c = ctx(hours=2)
    today = datetime.now(timezone.utc).date().isoformat()
    kept = postfilter(c, [job("Software Engineer", posted_at=ago(hours=9)), job("Software Engineer", posted=today)], log=lambda *a, **k: None)
    assert len(kept) == 1 and kept[0].posted == today


# --- the whole world --------------------------------------------------------

def test_worldwide_means_every_country_india_first():
    codes = job_bot.parse_countries("worldwide")
    assert codes[0] == "IN" and len(codes) > 20 and "DE" in codes and "US" in codes
    assert job_bot.is_worldwide("IN, worldwide") and not job_bot.is_worldwide("IN,DE")
    assert job_bot.parse_countries("IN,DE") == ["IN", "DE"]
