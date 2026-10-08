"""The live feed: reading LinkedIn's guest pages, merging ticks without duplicates, newest first,
and the local model only ever removing posts. No network here."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from naukri.jobs import live_feed as lf

NOW = datetime(2026, 10, 8, 6, 30, tzinfo=timezone.utc)

SEARCH = """<li><div class="base-card" data-entity-urn="urn:li:jobPosting:4477101573">
<a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/java-backend-4477101573?position=1"></a>
<h3 class="base-search-card__title">  Java Backend Developer </h3>
<h4 class="base-search-card__subtitle"><a class="hidden-nested-link">WillWare Technologies</a></h4>
<span class="job-search-card__location">Bengaluru, Karnataka, India</span>
<time class="job-search-card__listdate--new" datetime="2026-10-08">12 minutes ago</time></div></li>
<li><div data-entity-urn="urn:li:jobPosting:4477101999"><h3 class="base-search-card__title">Sales Executive</h3>
<h4 class="base-search-card__subtitle">Acme</h4><span class="job-search-card__location">Pune</span>
<time datetime="2026-10-08">5 minutes ago</time></div></li>
<li><div data-entity-urn="urn:li:jobPosting:4477102000"><h3 class="base-search-card__title">Senior Software Engineer</h3>
<h4 class="base-search-card__subtitle">Remote Co</h4><span class="job-search-card__location">India (Remote)</span>
<time datetime="2026-10-08">1 hour ago</time></div></li>"""

DETAIL = """<span class="num-applicants__caption">  66 applicants </span>
<div class="show-more-less-html__markup">We need 2-4 years of Java and Spring Boot. Visa sponsorship available.</div>
<h3 class="description__job-criteria-subheader">Seniority level</h3><span class="description__job-criteria-text">Entry level</span>
<h3 class="description__job-criteria-subheader">Employment type</h3><span class="description__job-criteria-text">Full-time</span>"""


def test_search_page_is_read_with_posting_times():
    jobs = lf.parse_search(SEARCH, NOW)
    assert [j["job_id"] for j in jobs] == ["4477101573", "4477101999", "4477102000"]
    j = jobs[0]
    assert j["title"] == "Java Backend Developer" and j["company"] == "WillWare Technologies" and j["location"].startswith("Bengaluru")
    assert j["posted_at"] == (NOW - timedelta(minutes=12)).isoformat(timespec="seconds")
    assert j["url"] == "https://www.linkedin.com/jobs/view/java-backend-4477101573"
    assert jobs[2]["workplace"] == "remote"
    assert lf.parse_search(SEARCH, NOW, "remote")[0]["workplace"] == "remote"
    assert lf.age_hours("just now") == 0 and lf.age_hours("2 days ago") == 48


def test_detail_page():
    d = lf.parse_detail(DETAIL)
    assert d["applicants"] == 66 and d["seniority"] == "Entry level" and d["employment"] == "Full-time"
    assert d["years_min"] == 2 and d["visa"] == "yes" and d["detailed"] is True


def test_merge_keeps_software_only_no_duplicates_newest_first():
    feed = {"items": []}
    new = lf.merge_jobs(feed, lf.parse_search(SEARCH, NOW), NOW)
    assert [j["job_id"] for j in new] == ["4477101573", "4477102000"]          # the sales job is not software
    # the next tick sees the same postings again: nothing new, earliest time kept
    again = lf.parse_search(SEARCH.replace("12 minutes ago", "14 minutes ago"), NOW + timedelta(minutes=2))
    assert lf.merge_jobs(feed, again, NOW + timedelta(minutes=2)) == []
    assert len(feed["items"]) == 2
    lf.prune(feed, NOW)
    assert [it["job_id"] for it in feed["items"]] == ["4477101573", "4477102000"]   # posted 12 min ago before 1 h ago
    lf.prune(feed, NOW + timedelta(hours=lf.FEED_HOURS + 2))
    assert feed["items"] == []


def test_the_model_only_removes_posts(tmp_path, monkeypatch):
    import json
    posts_dir = tmp_path / "data" / "posts"
    posts_dir.mkdir(parents=True)
    at = (NOW - timedelta(hours=1)).isoformat()
    hiring = "We are hiring Software Engineer (Backend), 1-3 years, Java. Bengaluru. Mail jobs@acme.example #hiring"
    seeker = "I am a fresher looking for a software developer job, please refer me #opentowork #hiring"
    (posts_dir / "linkedin_posts.json").write_text(json.dumps({"posts": [
        {"id": "1", "text": hiring, "posted_at": at, "author": "Acme HR", "url": "https://x/1"},
        {"id": "2", "text": seeker, "posted_at": at, "author": "Student", "url": "https://x/2"}]}), encoding="utf-8")
    monkeypatch.setattr(lf, "ROOT", tmp_path)
    monkeypatch.setattr(lf, "AI_CACHE_PATH", tmp_path / "data" / "live" / "ai_cache.json")
    # the model wrongly calls everything a software hiring post: the seeker must still stay out
    monkeypatch.setattr(lf, "ai_check", lambda p: {"hiring": True, "software": True, "min_years": None, "confidence": 0.99})
    monkeypatch.setattr(lf, "_ai", lambda: object())
    feed = {"items": []}
    assert lf.merge_posts(feed, NOW) == 1 and feed["items"][0]["company"] == "Acme HR"
    # the model saying "not software" with confidence removes a post the rules let through
    monkeypatch.setattr(lf, "ai_check", lambda p: {"hiring": True, "software": False, "min_years": None, "confidence": 0.9})
    monkeypatch.setattr(lf, "unsure", lambda p: True)
    (tmp_path / "data" / "live" / "ai_cache.json").unlink(missing_ok=True)
    feed2 = {"items": []}
    assert lf.merge_posts(feed2, NOW) == 0


def test_single_instance(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(lf, "DIR", tmp_path)
    monkeypatch.setattr(lf, "LOCK_PATH", tmp_path / "live.lock")
    assert lf.single_instance()                                   # no lock: taken
    (tmp_path / "live.lock").write_text(str(os.getppid()))        # a live process (pytest's parent) holds it
    assert not lf.single_instance()
    (tmp_path / "live.lock").write_text("999999")                 # a dead one: taken over
    assert lf.single_instance()
