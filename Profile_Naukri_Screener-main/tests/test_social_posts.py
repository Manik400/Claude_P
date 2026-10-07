"""The social hiring-posts watcher: the record shape every platform is read into, the parsers for
Telegram's preview page, Reddit's RSS, HN comments and Mastodon statuses, and the config merge.
No network here."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from naukri.jobs import linkedin_posts as lp
from naukri.jobs import social_posts as sp

NOW = datetime(2026, 10, 7, 6, tzinfo=timezone.utc)
HIRING = ("We are hiring Software Engineer (Backend) - freshers / 0-2 years, Java or Python, Bengaluru. "
          "CTC 6-8 LPA. Send your CV to careers@acme.example https://acme.example/apply #hiring")


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        pass


def test_record_has_the_phone_shape_and_the_platform():
    rec = sp.make_record("telegram", "chan-12", "https://t.me/chan/12", HIRING, NOW, author="Acme Jobs",
                         headline="Telegram channel @chan", reactions=120, query="@chan", now=NOW)
    assert rec["id"] == "telegram:chan-12" and rec["platform"] == "telegram" and rec["link_kind"] == "post"
    assert rec["hiring"] and lp.wanted(rec) and "careers@acme.example" in rec["emails"]
    assert rec["links"] == ["https://acme.example/apply"] and rec["posted_at"].startswith("2026-10-07T06:00")
    assert sp.make_record("x", "1", "u", "   ", NOW) is None


def test_telegram_preview_page_is_parsed(monkeypatch):
    page = """<html><body>
    <div class="tgme_widget_message" data-post="chan/12">
      <div class="tgme_widget_message_owner_name"><span>Acme Jobs</span></div>
      <div class="tgme_widget_message_text">%s<br/>Apply: <a href="https://acme.example/apply">link</a></div>
      <span class="tgme_widget_message_views">1.2K</span>
      <a class="tgme_widget_message_date" href="https://t.me/chan/12"><time datetime="2026-10-07T05:30:00+00:00"></time></a>
    </div>
    <div class="tgme_widget_message" data-post="chan/13"><div class="tgme_widget_message_text">I am a fresher looking for a job #opentowork</div>
      <time datetime="2026-10-07T05:40:00+00:00"></time></div>
    </body></html>""" % HIRING.replace("https://acme.example/apply", "")
    monkeypatch.setattr(sp, "_get", lambda *a, **k: _Resp(page))
    recs = sp.read_telegram("chan", NOW)
    assert len(recs) == 2
    first = recs[0]
    assert first["id"] == "telegram:chan-12" and first["url"] == "https://t.me/chan/12" and first["reactions"] == 1200
    assert first["author"] == "Acme Jobs" and "https://acme.example/apply" in first["links"] and lp.wanted(first)
    assert recs[1]["seeker"] and not lp.wanted(recs[1])


def test_reddit_rss_is_parsed(monkeypatch):
    feed = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
    <entry><author><name>/u/acme</name><uri>https://www.reddit.com/user/acme</uri></author>
      <content type="html">&lt;div&gt;%s&lt;/div&gt; submitted by /u/acme</content>
      <id>t3_abc12</id><link href="https://www.reddit.com/r/forhire/comments/abc12/hiring/"/>
      <published>2026-10-07T04:00:00+00:00</published><title>[Hiring] Backend engineer, remote</title></entry></feed>""" % HIRING.replace("&", "&amp;")
    monkeypatch.setattr(sp, "_get", lambda *a, **k: _Resp(feed))
    recs = sp.read_reddit("forhire", NOW)
    assert len(recs) == 1 and recs[0]["platform"] == "reddit" and recs[0]["text"].startswith("[Hiring] Backend engineer")
    assert "submitted by" not in recs[0]["text"] and recs[0]["headline"] == "r/forhire" and lp.wanted(recs[0])


def test_hn_thread_comments_become_posts(monkeypatch):
    calls = []

    def fake_get(url, params=None, **k):
        calls.append(params)
        if "author_whoishiring" in (params or {}).get("tags", ""):
            return _Resp(json.dumps({"hits": [{"objectID": "499", "title": "Ask HN: Who is hiring? (October 2026)"}]}))
        return _Resp(json.dumps({"nbPages": 1, "hits": [
            {"objectID": "5001", "parent_id": 499, "author": "acme", "created_at": "2026-10-07T03:00:00Z", "comment_text": "Acme | Backend Engineer | REMOTE | " + HIRING},
            {"objectID": "5002", "parent_id": 5001, "author": "x", "created_at": "2026-10-07T03:10:00Z", "comment_text": "Emailed you!"}]}))

    monkeypatch.setattr(sp, "_get", fake_get)
    recs = sp.read_hn(12, NOW)
    assert [r["id"] for r in recs] == ["hn:5001"] and recs[0]["url"].endswith("id=5001") and recs[0]["headline"].startswith("Ask HN")
    assert "story_499" in calls[1]["tags"]


def test_mastodon_statuses(monkeypatch):
    body = json.dumps([{"id": "7", "url": "https://mastodon.social/@acme/7", "created_at": "2026-10-07T05:00:00.000Z", "content": "<p>%s</p>" % HIRING,
                        "favourites_count": 3, "replies_count": 1, "account": {"display_name": "Acme", "acct": "acme", "url": "https://mastodon.social/@acme"}}])
    monkeypatch.setattr(sp, "_get", lambda *a, **k: _Resp(body))
    recs = sp.read_mastodon("mastodon.social", "hiring", NOW)
    assert recs[0]["id"] == "mastodon:7" and recs[0]["author"] == "Acme" and recs[0]["reactions"] == 3 and lp.wanted(recs[0])


def test_source_errors_do_not_end_the_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "read_telegram", lambda ch, now=None: (_ for _ in ()).throw(RuntimeError("private")))
    monkeypatch.setattr(sp, "read_reddit", lambda sub, now=None: [sp.make_record("reddit", sub, "https://r/" + sub, HIRING, NOW, headline="r/" + sub, now=NOW)])
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)
    cfg = sp.load_config(tmp_path / "none.yaml")
    cfg["telegram"]["channels"] = ["secret"]
    cfg["reddit"]["subreddits"] = ["forhire"]
    payload = sp.run_once(cfg, hours=12, sources=["telegram", "reddit"], do_publish=False, store_path=tmp_path / "store.json")
    assert payload["count"] == 1 and payload["platforms"] == ["reddit"] and payload["posts"][0]["platform"] == "reddit"
    store = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert store["pc"]["last_errors"] and "private" in store["pc"]["last_errors"][0] and store["sources"] == {"reddit": 1}


def test_config_merges_per_source(tmp_path):
    (tmp_path / "s.yaml").write_text("telegram:\n  channels: [a, b]\nx:\n  on: false\nevery_minutes: 45\n", encoding="utf-8")
    cfg = sp.load_config(tmp_path / "s.yaml")
    assert cfg["telegram"]["channels"] == ["a", "b"] and cfg["telegram"]["on"] is True
    assert cfg["x"]["on"] is False and cfg["x"]["queries"] and cfg["every_minutes"] == 45
    assert sp.load_config(tmp_path / "missing.yaml")["hn"]["on"] is True


def test_x_queries_rotate(tmp_path):
    store = sp.load_store(tmp_path / "s.json")
    assert sp._rotate(store, "x", ["a", "b", "c"], 2) == ["a", "b"]
    assert sp._rotate(store, "x", ["a", "b", "c"], 2) == ["c", "a"]
    assert sp.strip_html("<p>Hi&amp;<br>there</p>") == "Hi&\nthere"
