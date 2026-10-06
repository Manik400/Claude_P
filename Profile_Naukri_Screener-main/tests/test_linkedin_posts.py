"""The LinkedIn hiring-posts watcher: what counts as a hiring post for 0-2 years, how a post's
time is read, and how passes merge into one store. No browser here - the page side is one
JavaScript extractor; everything after it is plain functions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from naukri.jobs import linkedin_posts as lp


def test_activity_id_carries_the_post_time():
    # a 2025-era activity id: the top bits are the epoch in ms
    at = lp.activity_time("7380000000000000000")
    assert at is not None and 2025 <= at.year <= 2027
    assert lp.activity_time("12345") is None and lp.activity_time("abc") is None


def test_age_labels():
    assert lp.label_hours("3h •") == 3
    assert lp.label_hours("45m") == 0.75
    assert lp.label_hours("1d • Edited") == 24
    assert lp.label_hours("2w") == 336
    assert lp.label_hours("3 hours ago") == 3
    assert lp.label_hours("Just now") == 0
    assert lp.label_hours("Software Engineer at Acme") is None


FRESHER_POST = ("We are hiring! Software Engineer (Backend) - 2025 batch / freshers welcome, 0-2 years, Java or Python, "
                "Bengaluru (hybrid). CTC 6-8 LPA. Send your CV to careers@acme.example #hiring #freshers")
SENIOR_POST = "Hiring Senior Software Engineer, 6+ years in Java/Spring, lead a team. Pune. Apply now."
SEEKER_POST = "I am actively looking for a software engineer role, 2024 graduate, open to work. Any referrals appreciated! #opentowork"
QUIET_POST = "Hiring SDE for our platform team in Hyderabad. Share your resume at jobs@quiet.example"
OFF_POST = "We are hiring mechanical engineers for our plant in Chennai. Apply now."


def test_a_fresher_hiring_post_is_wanted_with_its_facts_read():
    info = lp.classify(FRESHER_POST)
    assert info["hiring"] and not info["seeker"] and info["fits_entry"]
    assert "software engineer" in info["roles"] and "backend" in info["roles"]
    assert info["exp"]["min"] == 0 and info["exp"]["max"] == 2 and info["exp"]["entry"]
    assert info["emails"] == ["careers@acme.example"]
    assert "java" in info["skills"] and "python" in info["skills"]
    assert "Bengaluru" in info["locations"] and "Hybrid" in info["locations"]
    assert info["batch"] == ["2025"]
    assert info["salary"] and info["salary"]["lpa"] == 8.0
    assert lp.wanted(info)


def test_a_senior_post_is_not_for_0_2_years():
    info = lp.classify(SENIOR_POST)
    assert info["hiring"] and info["roles"] and not info["fits_entry"]
    assert info["exp"]["min"] == 6
    assert not lp.wanted(info)


def test_a_job_seekers_post_is_not_a_hiring_post():
    info = lp.classify(SEEKER_POST)
    assert info["seeker"] and not lp.wanted(info)


OTW_POST = ("🚀 Open to Work | QA Automation Engineer I'm a Fresher QA Automation Engineer looking for an opportunity to start my career "
            "in Software Testing. Skills: Selenium, Playwright, Java. Looking for: QA Automation Engineer roles. Email: me@example.com "
            "#OpenToWork #Fresher #Hiring #QAJobs")


def test_a_seekers_post_full_of_hiring_hashtags_is_still_a_seekers_post():
    info = lp.classify(OTW_POST)
    assert info["seeker"] and not lp.wanted(info)
    # the Open-to-Work frame on the author decides even when the words do not
    assert lp.classify(QUIET_POST, open_to_work=True)["seeker"]
    assert lp.classify(QUIET_POST, headline="Seeking a software engineer role | Open to work")["seeker"]
    assert not lp.classify(QUIET_POST, headline="Talent Acquisition at Acme")["seeker"]


def test_a_hiring_post_that_says_nothing_about_experience_is_kept():
    info = lp.classify(QUIET_POST)
    assert info["hiring"] and info["roles"] == ["sde"] and info["fits_entry"] and lp.wanted(info)
    assert info["locations"] == ["Hyderabad"] and info["emails"] == ["jobs@quiet.example"]


def test_another_profession_is_dropped():
    info = lp.classify(OFF_POST)
    assert info["hiring"] and not info["roles"] and info["off_field"] and not lp.wanted(info)


def test_links_keep_forms_and_shortlinks_not_profiles_or_images():
    links = ["https://www.linkedin.com/in/someone/", "https://lnkd.in/abc", "https://forms.gle/xyz",
             "https://media.licdn.com/dms/image/x.png", "https://www.linkedin.com/feed/hashtag/?keywords=hiring",
             "https://boards.greenhouse.io/acme/jobs/1", "https://www.linkedin.com/jobs/view/123/"]
    assert lp.good_links(links, "https://www.linkedin.com/in/someone/") == [
        "https://lnkd.in/abc", "https://forms.gle/xyz", "https://boards.greenhouse.io/acme/jobs/1", "https://www.linkedin.com/jobs/view/123/"]


def test_read_card_builds_a_post_with_an_exact_time():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    pid = str(int((now - timedelta(hours=3)).timestamp() * 1000) << 22)
    card = {"id": pid, "author": "Riya HR", "headline": "Talent Acquisition at Acme", "sub": "3h •", "text": FRESHER_POST,
            "full": "Riya HR Talent Acquisition at Acme 3h • " + FRESHER_POST, "links": ["https://lnkd.in/abc"], "actor_url": "https://www.linkedin.com/in/riya/",
            "counts": "42 reactions 7 comments"}
    rec = lp.read_card(card, "hiring software engineer", now)
    assert rec["id"] == pid and rec["url"].endswith(pid + "/")
    assert rec["posted_at"].startswith("2026-10-06T09:00") and rec["age_label"] == "3h •"
    assert rec["reactions"] == 42 and rec["comments"] == 7 and rec["links"] == ["https://lnkd.in/abc"]
    assert rec["author"] == "Riya HR" and rec["query"] == "hiring software engineer" and lp.wanted(rec)


def test_read_card_falls_back_to_the_label_when_the_id_has_no_time():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    rec = lp.read_card({"id": "123456789012345", "author": "A", "sub": "5h", "text": QUIET_POST, "full": QUIET_POST, "links": []}, "q", now)
    assert rec["posted_at"].startswith("2026-10-06T07:00")


def test_read_card_on_the_new_markup_uses_the_component_key_and_the_authors_posts_page():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    card = {"idx": 3, "id": "roenB8CPShDKxgd1XwsVobrlp1JZBOzE7TVNnZOlh3U", "author": "Ranjan Makvana", "headline": "Senior Technical Recruiter",
            "sub": "Just now", "text": QUIET_POST, "full": "Ranjan Makvana • 3rd+ Senior Technical Recruiter Just now " + QUIET_POST,
            "links": ["https://www.linkedin.com/in/ranjan-makvana-861247230/"], "actor_url": "https://www.linkedin.com/in/ranjan-makvana-861247230/", "has_menu": True}
    rec = lp.read_card(card, "hiring SDE", now)
    assert rec["id"] == "roenB8CPShDKxgd1XwsVobrlp1JZBOzE7TVNnZOlh3U" and rec["posted_at"] == now.isoformat(timespec="seconds")
    assert rec["link_kind"] == "author" and rec["url"] == "https://www.linkedin.com/in/ranjan-makvana-861247230/recent-activity/all/"
    assert rec["fp"] == lp.fingerprint("Ranjan Makvana", QUIET_POST)
    # with the link copied from the control menu, that is the link
    rec2 = lp.read_card(dict(card, url="https://lnkd.in/p/abc"), "hiring SDE", now)
    assert rec2["url"] == "https://lnkd.in/p/abc" and rec2["link_kind"] == "post"
    assert lp.author_posts_url("https://www.linkedin.com/company/acme/") == "https://www.linkedin.com/company/acme/posts/"


def test_merge_treats_the_same_text_from_two_queries_as_one_post_and_keeps_a_real_link():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    store = {"posts": []}
    a = lp.read_card({"id": "keyA" * 6, "author": "A", "sub": "1h", "text": QUIET_POST, "full": "", "links": [], "actor_url": "https://www.linkedin.com/in/a/"}, "q1", now)
    b = lp.read_card({"id": "keyB" * 6, "author": "A", "sub": "1h", "text": QUIET_POST, "full": "", "links": [], "actor_url": "https://www.linkedin.com/in/a/", "url": "https://lnkd.in/p/x"}, "q2", now)
    assert lp.merge(store, [a], now) == 1
    assert lp.merge(store, [b], now) == 0
    p = store["posts"][0]
    assert p["id"] == a["id"] and p["queries"] == ["q1", "q2"] and p["url"] == "https://lnkd.in/p/x" and p["link_kind"] == "post"


def test_merge_dedups_by_post_and_forgets_old_ones():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    store = lp.load_store(__import__("pathlib").Path("does-not-exist.json"))
    a = {"id": "1", "posted_at": (now - timedelta(hours=1)).isoformat(), "queries": ["q1"], "first_seen": now.isoformat(), "last_seen": now.isoformat(), "text": "a"}
    old = {"id": "2", "posted_at": (now - timedelta(days=9)).isoformat(), "queries": ["q1"], "first_seen": now.isoformat(), "last_seen": now.isoformat(), "text": "old"}
    assert lp.merge(store, [a, old], now) == 2
    assert [p["id"] for p in store["posts"]] == ["1"]            # the nine-day-old post is gone
    again = dict(a, queries=["q2"], text="a (edited)", last_seen=(now + timedelta(minutes=30)).isoformat())
    assert lp.merge(store, [again], now + timedelta(minutes=30)) == 0
    p = store["posts"][0]
    assert p["queries"] == ["q1", "q2"] and p["text"] == "a (edited)" and p["first_seen"] == now.isoformat()


def test_payload_shows_only_wanted_posts_inside_the_window_newest_first():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    mk = lambda i, hours, text: dict(lp.classify(text), id=str(i), posted_at=(now - timedelta(hours=hours)).isoformat(), text=text, author="x", url="u")  # noqa: E731
    store = {"updated": now.isoformat(), "queries": ["q"], "pc": {"host": "PC"},
             "posts": [mk(1, 2, FRESHER_POST), mk(2, 20, FRESHER_POST), mk(3, 1, SENIOR_POST), mk(4, 0.5, QUIET_POST)]}
    out = lp.payload_for(store, 12, now)
    assert [p["id"] for p in out["posts"]] == ["4", "1"]
    assert out["count"] == 2 and out["seen_total"] == 4 and out["window_hours"] == 12
    assert out["posts"][0]["hours_old"] == 0.5 and "full" not in out["posts"][0]
    json.dumps(out)   # what goes to the phone is plain JSON


def test_links_written_in_the_text_are_read_and_get_is_a_role_only_in_capitals():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    text = "Amazon is hiring SDE I freshers. Apply here: https://lnkd.in/dnpNgui5, form lnkd.in/guNPiXtw. Get the details in comments."
    rec = lp.read_card({"id": "k" * 24, "author": "A", "sub": "1h", "text": text, "full": text, "links": []}, "q", now)
    assert rec["links"] == ["https://lnkd.in/dnpNgui5", "https://lnkd.in/guNPiXtw"]
    assert "graduate engineer trainee" not in rec["roles"] and "get" not in rec["roles"]
    assert "graduate engineer trainee" in lp.classify("Hiring GET - Graduate Engineer Trainee, B.Tech 2026, Java basics.")["roles"]
    assert lp.classify("We are hiring! Coding role for freshers with Java and SQL. Apply now.")["roles"] == ["software (general)"]


def test_a_repost_of_the_same_long_text_is_the_same_post():
    assert lp.fingerprint("Page A", FRESHER_POST) == lp.fingerprint("Someone Else", FRESHER_POST)
    assert lp.fingerprint("A", "short hiring note") != lp.fingerprint("B", "short hiring note")


def test_search_url_asks_for_the_last_day_newest_first():
    url = lp.search_url("hiring SDE")
    assert url.startswith("https://www.linkedin.com/search/results/content/?")
    assert "keywords=hiring+SDE" in url and "past-24h" in url and "date_posted" in url
