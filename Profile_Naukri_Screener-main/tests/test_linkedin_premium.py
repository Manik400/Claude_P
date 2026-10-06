"""The LinkedIn Premium runner: ranking, what is read off a job page, the daily budget, the drafts.
No browser here."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from naukri.jobs import linkedin_premium as lp


def test_recruiter_headlines():
    assert lp.is_recruiter("Technical Recruiter at Acme")
    assert lp.is_recruiter("Talent Acquisition Partner | Hiring backend engineers")
    assert lp.is_recruiter("Engineering Manager, Payments")
    assert not lp.is_recruiter("Software Engineer at Acme")
    assert not lp.is_recruiter("")


def test_page_readers():
    text = "Backend Engineer · Berlin · Reposted 3 hours ago · Over 100 applicants · You'd be a top applicant based on your profile"
    assert lp.applicants_of(text) == 101
    assert lp.posted_hours(text) == 3
    assert lp.TOP_APPLICANT_RX.search(text)
    assert lp.applicants_of("12 applicants") == 12
    assert lp.posted_hours("Posted 2 days ago") == 48
    assert lp.years_asked("3-5 years of Java; 7+ years preferred") == 3
    assert lp.years_asked("no experience needed") is None
    assert lp.is_abroad("Berlin, Germany") and not lp.is_abroad("Gurugram, Haryana, India") and not lp.is_abroad("Remote")


def test_sponsorship_without_jobhunt(monkeypatch):
    monkeypatch.setattr(lp, "_relocation_module", lambda: None)
    assert lp.sponsorship_of("x", "We offer visa sponsorship and a relocation package")["visa"] == "yes"
    assert lp.sponsorship_of("x", "Candidates must already have the right to work in the UK")["visa"] == "no"
    assert lp.sponsorship_of("x", "Great team")["visa"] == "unclear"


def test_rank_prefers_top_applicant_easy_apply_fresh_and_sponsored():
    cfg = dict(lp.DEFAULTS)
    card = {"title": "Backend Engineer", "easy_apply": True}
    good = {"top_applicant": True, "applicants": 10, "posted_hours": 2, "abroad": True, "sponsorship": {"visa": "yes", "relocation": "yes"}}
    s1, why = lp.rank(card, good, cfg)
    assert s1 >= 100 and "top applicant" in why and "visa sponsorship" in why
    s2, _ = lp.rank(card, {"top_applicant": False, "applicants": 300, "posted_hours": 400, "abroad": True, "sponsorship": {"visa": "no"}}, cfg)
    assert s2 < s1 and s2 < 10
    assert lp.rank({"title": "Senior Staff Engineer"}, {}, cfg)[0] < 0
    assert lp.rank(card, {"years_asked": 7}, cfg)[0] < 0
    assert lp.rank(card, {"exclude": "closed"}, cfg)[0] < 0


def test_apply_budget_is_the_smaller_of_own_and_shared_caps():
    cfg = {"apply_per_day": 8}
    assert lp.apply_budget(cfg, {"applied": 0}, 25, 0) == 8
    assert lp.apply_budget(cfg, {"applied": 6}, 25, 0) == 2
    assert lp.apply_budget(cfg, {"applied": 0}, 25, 23) == 2
    assert lp.apply_budget(cfg, {"applied": 8}, 25, 0) == 0
    assert lp.apply_budget(cfg, {"applied": 0}, 25, 30) == 0


def test_days_left_and_premium_over():
    cfg = {"until": "2026-10-30"}
    assert lp.days_left(cfg, date(2026, 10, 7)) == 23
    assert not lp.premium_over(cfg, date(2026, 10, 30))
    assert lp.premium_over(cfg, date(2026, 10, 31))


def test_pick_posts_to_like_freshest_hiring_posts_not_yet_liked():
    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)

    def post(i, hours, reactions=0, **kw):
        return dict({"url": f"https://www.linkedin.com/feed/update/urn:li:activity:{i}/", "link_kind": "post", "author": f"a{i}",
                     "posted_at": (now - timedelta(hours=hours)).isoformat(), "reactions": reactions, "text": "hiring"}, **kw)

    store = {"posts": [post(1, 2, 5), post(2, 50, 90), post(3, 1, 40), post(4, 3, 99, open_to_work=True), post(5, 4, 70, link_kind="author")]}
    picks = lp.pick_posts_to_like(store, {store["posts"][0]["url"]: "2026-10-06"}, 2, now=now)
    assert [p["author"] for p in picks] == ["a3"]        # a1 liked already, a2 too old, a4 is a seeker, a5 has no post link


def test_draft_is_written_from_the_template_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "_localai", lambda: None)
    monkeypatch.setattr(lp, "DRAFTS_DIR", tmp_path / "drafts")
    state = {"draft_index": 3}
    me = {"name": "Manik", "role": "Backend Software Engineer", "stack": "Java, Kafka", "resume": ""}
    path = lp.write_draft(dict(lp.DEFAULTS), state, me, datetime(2026, 10, 7, 9))
    text = path.read_text(encoding="utf-8")
    assert lp.TOPICS[3]["hook"] in text and "#Java" in text and "template" in text
    assert (tmp_path / "drafts" / "TODAY.md").exists()
    assert state["draft_index"] == 4 and state["days"]["2026-10-07"]["drafted"] == 1
    assert lp.topic_for(len(lp.TOPICS) + 1) is lp.TOPICS[1]      # the rotation wraps


def test_inmail_and_note_are_short(monkeypatch):
    monkeypatch.setattr(lp, "_localai", lambda: None)
    me = {"name": "Manik", "role": "Backend Software Engineer", "stack": "Java, Kafka, PostgreSQL, AWS", "resume": ""}
    text = lp.inmail_draft({"title": "Backend Engineer", "company": "Acme"}, {"name": "Priya Sharma"}, me)
    assert text.startswith("Hi Priya") and len(text.split()) <= 85
    note = lp.connection_note({"name": "Priya Sharma"}, me)
    assert note.startswith("Hi Priya") and len(note) <= 280


def test_report_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(lp, "DIR", tmp_path)
    state = {"reach": [{"date": "2026-10-07", "profile_views": 12, "post_impressions": 300, "search_appearances": 9}]}
    d = lp.day(state, datetime(2026, 10, 7, 9))
    d["applied_jobs"].append({"score": 80, "title": "Backend Engineer", "company": "Acme", "location": "Berlin", "why": ["top applicant"],
                              "url": "https://www.linkedin.com/jobs/view/1/", "status": "applied"})
    d["leads"].append({"name": "Priya", "headline": "Recruiter", "url": "https://www.linkedin.com/in/p/", "note": "Hi"})
    d["inmails"].append({"to": "Raj", "headline": "EM", "person_url": "u", "job": "SDE", "company": "Acme", "job_url": "j", "text": "Hi Raj"})
    path = lp.write_report({"until": "2026-10-30"}, state, datetime(2026, 10, 7, 9))
    text = path.read_text(encoding="utf-8")
    assert "23 day(s) of Premium left" in text and "Backend Engineer" in text and "Priya" in text and "Hi Raj" in text
    assert "Abroad" in text and (tmp_path / "LATEST.md").exists()
    assert json.loads(json.dumps(state))    # the state stays JSON-serialisable
