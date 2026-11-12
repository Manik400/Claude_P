"""Career OS directive V2.0 (career/CAREER_OS_DIRECTIVE.md), the parts this bot implements in code:

  * a "senior" title with no stated experience is a stretch, never a "no" (rules 3-4);
    a posting that STATES a number is still judged on that number;
  * every job gets the directive's class A / B / C / D, derived from the fit label;
  * every job gets a freshness label, and a posting with no date is "Unknown date";
  * jobbot.compliance answers each platform's mode from career/career_profile.json and
    never says automation is allowed unless that file says so.

Nothing here touches the network.  Run from job-hunt/:  python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import careers_bot  # noqa: E402
from jobbot import compliance, dates, experience  # noqa: E402
from jobbot.experience import annotate, classify_fit, exp_class, seniority_from_title  # noqa: E402
from jobbot.models import Job  # noqa: E402
from jobbot.search import apply_fit_filter  # noqa: E402

YEARS = 2.2   # the candidate (career_profile.json -> candidate.total_experience_years)


def job(title="Software Engineer", **kw):
    base = dict(source="x", source_name="X", title=title, company="Acme",
                url="https://example.com/" + title.replace(" ", "-"), country="IN")
    base.update(kw)
    return Job(**base).finalize()


# ----------------------------------------------------------------- item 4: senior titles

def test_senior_title_with_no_stated_number_is_a_stretch_not_a_no():
    sen = seniority_from_title("Senior Software Engineer")
    assert sen[0] == "senior"
    assert classify_fit(YEARS, None, None, sen) == "stretch"
    assert classify_fit(0.0, None, None, sen) == "stretch"       # however short: never "no" on the title alone
    assert classify_fit(1.5, None, None, sen) == "stretch"       # what --experience 0-3 resolves to


def test_senior_title_is_still_a_fit_for_someone_with_the_years():
    assert classify_fit(6.0, None, None, seniority_from_title("Senior Software Engineer")) == "fit"


@pytest.mark.parametrize("title", ["Sr. Backend Developer", "Senior Backend Engineer", "Senior .NET Developer"])
def test_annotate_keeps_senior_titles_out_of_the_no_bucket(title):
    j = annotate(job(title), YEARS)
    assert j.seniority == "senior" and j.exp_min is None and j.exp_max is None
    assert j.fit == "stretch"
    assert apply_fit_filter([j], "default") == [j]               # the default filter no longer drops it


def test_a_stated_number_still_decides_whatever_the_title_says():
    far = annotate(job("Senior Software Engineer", description="We need 6+ years of experience in backend development."), YEARS)
    assert (far.exp_min, far.exp_max) == (6.0, None) and far.fit == "no"
    near = annotate(job("Senior Software Engineer", description="2-3 years of experience with Java."), YEARS)
    assert near.fit == "fit"
    slightly = annotate(job("Senior Software Engineer", description="Minimum 4 years of experience."), YEARS)
    assert slightly.fit == "stretch"
    # and without a senior title the same numbers give the same answers
    assert annotate(job("Software Engineer", description="We need 6+ years of experience in backend development."), YEARS).fit == "no"


def test_lead_principal_staff_titles_with_no_number_are_judged_as_before():
    for title in ("Lead Engineer", "Principal Engineer", "Staff Software Engineer", "Senior Lead Engineer"):
        assert classify_fit(YEARS, None, None, seniority_from_title(title)) == "no", title


def test_the_other_fit_labels_are_unchanged():
    assert classify_fit(None, 2, 4, None) == "unknown"            # no candidate experience given
    assert classify_fit(YEARS, None, None, None) == "unknown"     # nothing stated, plain title
    assert classify_fit(YEARS, 0, 3, None) == "fit"
    assert classify_fit(YEARS, 2, None, None) == "fit"
    assert classify_fit(YEARS, 4, None, None) == "stretch"        # 1.8 short
    assert classify_fit(YEARS, 5, None, None) == "no"             # 2.8 short, stated
    assert classify_fit(8.0, 0, 2, None) == "over"
    assert classify_fit(YEARS, None, None, seniority_from_title("Software Engineering Intern")) == "over"
    assert classify_fit(YEARS, None, None, seniority_from_title("Junior Developer")) == "fit"


def test_careers_bot_range_fit_follows_the_same_rule():
    sen = seniority_from_title("Senior Software Engineer")
    assert careers_bot.fit_for_range(0.0, 2.0, None, None, sen) == "stretch"     # was "no" (5 - 2 > 2)
    assert careers_bot.fit_for_range(0.0, 3.0, None, None, sen) == "stretch"
    assert careers_bot.fit_for_range(0.0, 3.0, 6.0, None, sen) == "no"           # stated number decides
    assert careers_bot.fit_for_range(0.0, 3.0, 3.0, 5.0, None) == "fit"          # asking up to 3 passes
    assert careers_bot.fit_for_range(0.0, 3.0, None, None, seniority_from_title("Principal Engineer")) == "no"


# ----------------------------------------------------------------- item 5: A / B / C / D

def test_exp_class_mapping():
    assert exp_class("fit", 2, 3) == "A"
    assert exp_class("fit", None, 3) == "A"
    assert exp_class("fit") == "B"            # a fit read off the title only: nothing was stated
    assert exp_class("unknown") == "B"
    assert exp_class("over", 0, 0) == "B"     # asks for less than the candidate has: not a mismatch
    assert exp_class("stretch", 4, None) == "C"
    assert exp_class("stretch") == "C"
    assert exp_class("no", 8, None) == "D"
    assert exp_class("something-else") == ""
    assert experience.exp_class_label("A") == "DIRECT MATCH"
    assert experience.exp_class_label("B") == "STRONG POTENTIAL MATCH"
    assert experience.exp_class_label("C") == "STRETCH OPPORTUNITY"
    assert experience.exp_class_label("D") == "EXPERIENCE MISMATCH"
    assert experience.exp_class_label("") == ""


def test_exp_class_labels_match_the_career_profile():
    with open(compliance.DEFAULT_PATH, encoding="utf-8") as f:
        wanted = {k: v["label"] for k, v in json.load(f)["classification"].items() if not k.startswith("_")}
    assert experience.EXP_CLASS_LABELS == wanted


def test_annotate_sets_the_class_on_the_job():
    a = annotate(job("Software Engineer", description="1-3 years of experience in C#."), YEARS)
    assert (a.fit, a.exp_class, a.exp_class_label) == ("fit", "A", "DIRECT MATCH")
    b = annotate(job("Backend Developer", description="Build APIs with us."), YEARS)
    assert (b.fit, b.exp_class, b.exp_class_label) == ("unknown", "B", "STRONG POTENTIAL MATCH")
    c = annotate(job("Senior Backend Engineer"), YEARS)
    assert (c.fit, c.exp_class, c.exp_class_label) == ("stretch", "C", "STRETCH OPPORTUNITY")
    d = annotate(job("Software Engineer", description="At least 8 years of experience required."), YEARS)
    assert (d.fit, d.exp_class, d.exp_class_label) == ("no", "D", "EXPERIENCE MISMATCH")


def test_no_class_is_claimed_when_the_candidate_experience_is_unknown():
    j = annotate(job("Software Engineer", description="1-3 years of experience in C#."), None)
    assert j.fit == "unknown" and j.exp_class == "" and j.exp_class_label == ""


def test_class_and_freshness_are_written_to_jobs_json_and_old_files_still_load(tmp_path):
    import job_bot
    j = annotate(job("Senior Backend Engineer", posted=str(datetime.now(timezone.utc).date())), YEARS)
    job_bot.save_run(str(tmp_path), {"roles": ["x"]}, [], [j])
    with open(tmp_path / "jobs.json", encoding="utf-8") as f:
        rows = json.load(f)
    assert rows[0]["exp_class"] == "C" and rows[0]["exp_class_label"] == "STRETCH OPPORTUNITY"
    assert rows[0]["freshness"] == "Very fresh" and rows[0]["fit"] == "stretch"
    back = Job.from_dict(rows[0])
    assert (back.exp_class, back.freshness) == ("C", "Very fresh")
    # a jobs.json written before these fields existed
    old = {k: v for k, v in rows[0].items() if k not in ("exp_class", "exp_class_label", "freshness")}
    loaded = Job.from_dict(old)
    assert loaded.exp_class == "" and loaded.exp_class_label == "" and loaded.fit == "stretch"
    assert loaded.to_dict()["freshness"] == "Very fresh"          # recomputed from the date it does have


def test_strict_drops_stretch_and_default_keeps_it():
    """Why the scheduled searches moved from fit=strict to fit=default."""
    jobs = [annotate(job("Senior Backend Engineer"), YEARS),                                       # C
            annotate(job("Backend Developer", description="Build APIs with us."), YEARS),          # B
            annotate(job("Software Engineer", description="1-3 years of experience in C#."), YEARS),  # A
            annotate(job("Software Engineer", description="At least 8 years of experience required."), YEARS)]  # D
    assert [j.exp_class for j in apply_fit_filter(jobs, "strict")] == ["A"]
    assert [j.exp_class for j in apply_fit_filter(jobs, "default")] == ["C", "B", "A"]
    assert len(apply_fit_filter(jobs, "all")) == 4


def test_scheduled_searches_keep_stretch_jobs_and_every_earlier_role():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "site", "scheduled_searches.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    for kind in ("jobhunt", "careers"):
        for entry in cfg[kind]:
            assert entry["fit"] == "default", entry
            assert entry["experience"] == "0-3", entry
    roles = [r.strip().lower() for r in cfg["roles"].split(",")]
    assert len(roles) == len(set(roles))
    before = ("engineer, senior software developer, SSE, SDE II, SDE 2, senior software engineer, software engineer II, "
              "software engineer 2, software engineer, software developer, backend engineer, backend developer, "
              "full stack engineer, full stack developer, frontend engineer, frontend developer, java developer, SWE, SDE")
    for r in before.split(","):
        assert r.strip().lower() in roles, r
    for r in ("senior backend engineer", ".net developer", "c# developer", "spring boot developer", "api developer"):
        assert r in roles, r


# ----------------------------------------------------------------- item 6: freshness

TODAY = date(2026, 11, 11)


@pytest.mark.parametrize("days, label", [
    (0, "Very fresh"), (3, "Very fresh"),
    (4, "Fresh"), (7, "Fresh"),
    (8, "Recent"), (14, "Recent"),
    (15, "Older but potentially active"), (30, "Older but potentially active"),
    (31, "Verify before recommending"), (400, "Verify before recommending"),
])
def test_freshness_bands(days, label):
    posted = (TODAY - timedelta(days=days)).isoformat()
    assert dates.freshness_label(posted, today=TODAY) == label


def test_freshness_never_invents_a_date():
    for nothing in (None, "", "   ", "3 days ago", "not a date", "2026-13-45"):
        assert dates.freshness_label(nothing, today=TODAY) == "Unknown date", nothing
    assert dates.freshness_label("2027-01-01", today=TODAY) == "Unknown date"      # weeks in the future: not a posting date
    assert dates.freshness_label("2026-11-12", today=TODAY) == "Very fresh"        # a day ahead is a timezone


def test_freshness_reads_timestamps_and_other_today_types():
    assert dates.freshness_label("2026-11-06T09:30:00+00:00", today=TODAY) == "Fresh"
    assert dates.freshness_label("2026-11-06", today=datetime(2026, 11, 11, 23, 0)) == "Fresh"
    assert dates.freshness_label("2026-11-06", today="2026-11-11") == "Fresh"
    assert dates.freshness_label(str(datetime.now(timezone.utc).date())) == "Very fresh"   # default today


def test_freshness_bands_match_the_career_profile():
    with open(compliance.DEFAULT_PATH, encoding="utf-8") as f:
        wanted = tuple((b["max_days"], b["label"]) for b in json.load(f)["freshness"])
    assert dates.FRESHNESS_BANDS == wanted


def test_job_freshness_field_follows_the_date_it_holds():
    undated = job("Software Engineer")
    assert undated.freshness == "Unknown date" and undated.to_dict()["freshness"] == "Unknown date"
    old = job("Software Engineer", posted=(datetime.now(timezone.utc).date() - timedelta(days=45)).isoformat())
    assert old.freshness == "Verify before recommending"
    # a date found later (dedup, or the posting's own page) shows up when the job is written out
    undated.posted = (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat()
    assert undated.to_dict()["freshness"] == "Recent"


# ----------------------------------------------------------------- item 8: compliance

def test_compliance_reads_the_real_career_profile():
    assert os.path.isfile(compliance.DEFAULT_PATH)
    assert compliance.mode("linkedin") == "manual_assist"
    assert compliance.automation_allowed("linkedin") is False
    assert compliance.may_automate("linkedin") is False
    for spelling in ("LinkedIn", " linkedin ", "apify-linkedin", "linkedin_web", "linkedin.com"):
        assert compliance.mode(spelling) == "manual_assist", spelling
    assert compliance.mode("greenhouse") == "automation_permitted" and compliance.may_automate("greenhouse") is True
    assert compliance.mode("lever") == "automation_permitted" and compliance.automation_allowed("lever") is True
    for links in ("naukri", "indeed", "glassdoor"):
        assert compliance.mode(links) == "links_only" and compliance.automation_allowed(links) is False
    assert compliance.mode("ashby") == "evaluate" and compliance.automation_allowed("ashby") is False
    # null in the file = not evaluated: reported as None, and never as permission
    assert compliance.mode("wellfound") == "evaluate"
    assert compliance.automation_allowed("wellfound") is None and compliance.may_automate("wellfound") is False
    assert compliance.mode("relocateme") == "evaluate"                 # the bot's source key
    assert compliance.mode("company_career_sites") == "evaluate_per_site"
    assert compliance.verified_on("linkedin") is None


def test_compliance_unknown_platform_and_missing_file_never_allow(tmp_path):
    assert compliance.mode("some-new-board") == "unknown"
    assert compliance.automation_allowed("some-new-board") is None
    assert compliance.may_automate("some-new-board") is False
    assert compliance.mode("_rule") == "unknown"                       # a note in the file, not a platform
    missing = str(tmp_path / "nope.json")
    assert compliance.load_platforms(missing) == {}
    assert compliance.mode("greenhouse", path=missing) == "unknown"
    assert compliance.may_automate("greenhouse", path=missing) is False
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert compliance.may_automate("greenhouse", path=str(broken)) is False


def test_compliance_uses_the_file_it_is_given(tmp_path, monkeypatch):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({"platforms": {"_rule": "x", "linkedin": {"mode": "manual_assist", "automation_allowed": False},
                                           "acme": {"mode": "automation_permitted", "automation_allowed": True,
                                                    "verified_on": "2026-11-01"},
                                           "odd": {"mode": "evaluate", "automation_allowed": "yes"}}}), encoding="utf-8")
    assert compliance.mode("acme", path=str(p)) == "automation_permitted"
    assert compliance.may_automate("acme", path=str(p)) is True
    assert compliance.verified_on("acme", path=str(p)) == "2026-11-01"
    assert compliance.automation_allowed("odd", path=str(p)) is None    # only a real true / false counts
    assert compliance.entry("acme", path=str(p))["mode"] == "automation_permitted"
    assert [row[0] for row in compliance.summary(str(p))] == ["acme", "linkedin", "odd"]
    monkeypatch.setenv("CAREER_PROFILE_PATH", str(p))
    assert compliance.mode("acme") == "automation_permitted" and compliance.mode("greenhouse") == "unknown"


def test_compliance_platform_for_url():
    assert compliance.platform_for_url("https://www.linkedin.com/jobs/view/123") == "linkedin"
    assert compliance.platform_for_url("https://in.linkedin.com/jobs/view/123") == "linkedin"
    assert compliance.platform_for_url("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert compliance.platform_for_url("https://jobs.lever.co/acme/1") == "lever"
    assert compliance.platform_for_url("https://jobs.ashbyhq.com/acme/1") == "ashby"
    assert compliance.platform_for_url("https://www.naukri.com/job-listings-x") == "naukri"
    assert compliance.platform_for_url("https://notlinkedin.com/jobs") == ""
    assert compliance.platform_for_url("https://careers.acme.com/jobs/1") == ""
    assert compliance.platform_for_url("") == "" and compliance.platform_for_url(None) == ""


def test_compliance_is_advisory_the_linkedin_source_is_still_registered():
    """The directive marks LinkedIn manual-assist; the owner asked that nothing be switched off.
    This pins that: the helper exists, and the sources it disagrees with are still there."""
    from jobbot.sources import ALL_SOURCES
    assert "linkedin" in {s.key for s in ALL_SOURCES}
    assert compliance.may_automate("linkedin") is False


# --- a search range is not the candidate's experience ---------------------------------
def test_range_uses_the_profiles_real_years_when_inside_it():
    from jobbot.experience import candidate_years, classify_fit
    assert candidate_years("0-3", profile=2.2) == 2.2
    assert candidate_years("0-3 years", profile=2.2) == 2.2
    assert candidate_years("0-2", profile=2.2) == 1.0      # outside the range: midpoint, as before
    assert candidate_years("2.2", profile=9.0) == 2.2      # a single figure is taken as given
    assert candidate_years("5+", profile=2.2) == 5.0
    assert candidate_years(None, profile=2.2) is None
    # the point of it: "2-3 years" is a fit for 2.2 years, where the 1.5 midpoint said stretch
    assert classify_fit(candidate_years("0-3", profile=2.2), 2.0, 3.0, None) == "fit"
    assert classify_fit(1.5, 2.0, 3.0, None) == "stretch"


def test_profile_years_reads_the_career_profile():
    from jobbot.experience import candidate_years, profile_years
    assert profile_years() == 2.2
    assert profile_years("no/such/file.json") is None
    assert candidate_years("0-3") == 2.2
