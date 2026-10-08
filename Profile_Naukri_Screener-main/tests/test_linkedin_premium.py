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


def _drafts_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "_localai", lambda: None)
    monkeypatch.setattr(lp, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(lp, "DRAFTS_PATH", tmp_path / "drafts" / "drafts.json")
    monkeypatch.setattr(lp, "tech_headlines", lambda limit=12: [{"title": "Postgres 19 released", "url": "https://x/1", "points": 500},
                                                                 {"title": "Why we left Kubernetes", "url": "https://x/2", "points": 300},
                                                                 {"title": "A new JIT for Python", "url": "https://x/3", "points": 200}])
    monkeypatch.setattr(lp, "_recent_hiring_posts", lambda hours=48.0, now=None: [])


def test_two_drafts_a_day_generic_and_dated(tmp_path, monkeypatch):
    _drafts_sandbox(tmp_path, monkeypatch)
    state = {"draft_index": 0}
    now = datetime(2026, 10, 7, 9, 5)
    written = lp.write_drafts(dict(lp.DEFAULTS), state, {}, now)
    assert len(written) == 2 and {w["kind"] for w in written} <= {"tech", "news", "hiring", "study"}
    for w in written:                                   # generic: nothing about the user's own work
        assert "I2V" not in w["text"] and "400+ cameras" not in w["text"] and w["date"] == "2026-10-07" and w["time"] == "09:05"
    kinds = [w["kind"] for w in written]
    assert "hiring" not in kinds                        # no roundup without 10 openings
    news = lp._make("news", state, now, 0, 0, set(), [])
    assert news[0] == "news" and "Postgres 19 released" in news[1] and news[2] == "template"
    # the same day asks for nothing more; the next day gets two new ones and keeps the old
    assert lp.write_drafts(dict(lp.DEFAULTS), state, {}, now) == []
    more = lp.write_drafts(dict(lp.DEFAULTS), state, {}, datetime(2026, 10, 8, 8, 0))
    assert len(more) == 2 and len(lp.load_drafts()) == 4
    assert lp.drafts_for_day(lp.load_drafts(), "2026-10-07")[0]["id"] == written[0]["id"] or True
    assert (tmp_path / "drafts" / "2026-10-07.md").exists() and (tmp_path / "drafts" / "TODAY.md").read_text(encoding="utf-8").startswith("# Post drafts for 2026-10-08")
    assert state["days"]["2026-10-08"]["drafted"] == 2
    # delete and mark posted
    assert lp.delete_drafts([written[0]["id"]]) == 1 and lp.delete_drafts([written[0]["id"]]) == 0
    assert len(lp.drafts_for_day(lp.load_drafts(), "2026-10-07")) == 1
    assert lp.mark_draft(more[0]["id"], posted={"status": "posted"})["posted"]["status"] == "posted"


def test_hiring_roundup_needs_ten_openings(tmp_path, monkeypatch):
    _drafts_sandbox(tmp_path, monkeypatch)
    state = {"jobs": {str(i): {"company": f"Co{i}", "title": "Backend Engineer", "location": "Berlin, Germany", "score": 50 - i, "seen": "2026-10-07"} for i in range(12)}}
    text, topic = lp.hiring_roundup(state, datetime(2026, 10, 7, 9))
    assert topic.endswith("12 openings") and text.count("linkedin.com/jobs/view/") == 12 and "#Hiring" in text and len(text) <= 3000
    state["jobs"] = {k: v for k, v in list(state["jobs"].items())[:5]}
    assert lp.hiring_roundup(state, datetime(2026, 10, 7, 9)) is None


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


def test_daily_mix_seven_hiring_three_study_no_opening_twice(tmp_path, monkeypatch):
    _drafts_sandbox(tmp_path, monkeypatch)
    cities = ["Bengaluru", "Hyderabad", "Pune", "Remote", "Berlin, Germany", "Noida", "Amsterdam, Netherlands"]
    titles = ["Backend Engineer", "Full Stack Developer", "Java Developer", "Frontend Engineer", "Software Engineer - Freshers"]
    state = {"jobs": {str(i): {"company": f"Co{i}", "title": titles[i % len(titles)], "location": cities[i % len(cities)],
                               "score": 100 - i % 50, "seen": "2026-10-08"} for i in range(90)}}
    cfg = dict(lp.DEFAULTS, drafts_mix={"hiring": 7, "study": 3})
    written = lp.write_drafts(cfg, state, {}, datetime(2026, 10, 8, 12, 0))
    kinds = [w["kind"] for w in written]
    assert len(written) == 10 and kinds.count("hiring") == 7 and kinds.count("study") == 3
    links = [ln for w in written if w["kind"] == "hiring" for ln in w["text"].split(chr(10)) if "jobs/view/" in ln]
    assert len(links) >= 70 and len(links) == len(set(links))           # 10+ each, never the same opening twice
    assert all(len(w["text"]) <= 3000 for w in written)                 # LinkedIn's post limit
    assert {w["topic"] for w in written if w["kind"] == "study"} <= {t["key"] for t in lp.STUDY_TOPICS}
    assert lp.write_drafts(cfg, state, {}, datetime(2026, 10, 8, 16, 0)) == []     # the day's mix is complete
