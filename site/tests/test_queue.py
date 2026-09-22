"""The one auto-apply queue: how phone requests fold into it, how progress is
counted, and how the PC's ledger drives every item's status.

Run from site/:  python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import phone_apply as pa  # noqa: E402

# The site publishes plain .json now; `passphrase` survives on the worker's
# signatures only so it can still read files from the old encrypted branch.
PASS = ""


def li(n, **kw):
    d = {"source": "linkedin", "title": "Backend Engineer %s" % n, "company": "Acme", "url": "https://www.linkedin.com/jobs/view/%s/" % n,
         "location": "Pune", "score": 70, "fit": "fit", "extra": {}}
    d.update(kw)
    return d


def nk(n, **kw):
    d = {"source": "naukri", "title": "Python Dev %s" % n, "company": "Infosys", "url": "https://www.naukri.com/job-listings-python-dev-%s" % n,
         "score": 80, "fit": "unknown", "extra": {"naukri_id": str(n), "company_apply": False, "has_questionnaire": True}}
    d.update(kw)
    return d


def web(url, **kw):
    d = {"source": "seek", "title": "Engineer", "company": "Atlassian", "url": url, "score": 66, "extra": {}}
    d.update(kw)
    return d


class Stub:
    """Stands in for the Naukri screener's dashboard / questions modules."""
    def __init__(self):
        self.pending = [{"question": "Notice period?", "answer": ""}]
        self.saved = []

    # questions
    def load_pending(self):
        return self.pending

    def save_pending(self, entries):
        self.pending = entries

    @staticmethod
    def key(q):
        return q.strip().lower()

    # dashboard
    def save_answers(self, payload):
        self.saved.append(("answers", payload))

    def save_note(self, payload):
        self.saved.append(("note", payload))


@pytest.fixture
def pages(tmp_path):
    """A gh-pages checkout with one worldwide report, one Naukri scan, both with job lists."""
    jobs_dir = tmp_path / "data" / "jobhunt"
    jobs_dir.mkdir(parents=True)
    (tmp_path / "data" / "naukri").mkdir()
    world = [li(111), li(222, fit="no"), li(333, score=40), web("https://www.seek.com.au/job/9")]
    nauk = [nk(5001), nk(5002, score=30)]
    (jobs_dir / "r1.jobs.json").write_bytes(json.dumps(world).encode())
    (tmp_path / "data" / "naukri" / "n1.jobs.json").write_bytes(json.dumps(nauk).encode())
    (tmp_path / "data" / "index.json").write_text(json.dumps({"items": [
        {"id": "r1", "kind": "jobhunt", "title": "python dev", "meta": {"jobs_file": "data/jobhunt/r1.jobs.json"}},
        {"id": "n1", "kind": "naukri", "title": "Naukri openings", "meta": {"jobs_file": "data/naukri/n1.jobs.json"}},
    ]}))
    return str(tmp_path)


def test_job_key_names_every_board_the_same_way_as_the_phone():
    assert pa.job_key(li(111))[:2] == ("linkedin:111", "linkedin")
    assert pa.job_key(nk(5001))[:2] == ("naukri:5001", "naukri")
    key, board, _ = pa.job_key(web("https://example.com/jobs/123"))
    assert board == "web" and key == "web:488d9f4bx"     # same djb2 the phone computes


def test_queue_all_from_a_report_skips_no_fit_and_dedups(pages):
    q = {"items": [], "paused": False, "settings": {}}
    stub = Stub()
    reqs = [("a.json", "", {"type": "queue", "payload": {"report": "r1", "jobs": "all"}}),
            ("b.json", "", {"type": "queue", "payload": {"report": "r1", "jobs": "all"}})]
    pa.apply_requests(q, reqs, pages, PASS, stub, stub)
    keys = sorted(i["key"] for i in q["items"])
    assert keys == ["linkedin:111", "linkedin:333", "web:" + pa._djb2("https://www.seek.com.au/job/9")]
    assert all(i["status"] == "queued" for i in q["items"])
    assert q["items"][0]["source"]["kind"] == "jobhunt"


def test_selected_keys_and_company_site_items_from_the_payload(pages):
    q = {"items": [], "paused": False, "settings": {}}
    stub = Stub()
    payload = {"report": "n1", "jobs": ["naukri:5001"],
               "items": [{"url": "https://boards.greenhouse.io/x/jobs/1", "title": "SRE", "company": "X"}]}
    pa.apply_requests(q, [("a.json", "", {"type": "queue", "payload": payload})], pages, PASS, stub, stub)
    by = {i["key"]: i for i in q["items"]}
    assert set(by) == {"naukri:5001", "web:" + pa._djb2("https://boards.greenhouse.io/x/jobs/1")}
    assert by["naukri:5001"]["has_questionnaire"] is True


def test_remove_retry_pause_settings_and_answers(pages):
    q = {"items": [], "paused": False, "settings": {}}
    stub = Stub()
    pa.apply_requests(q, [("a.json", "", {"type": "queue", "payload": {"report": "r1", "jobs": "all"}})], pages, PASS, stub, stub)
    item = next(i for i in q["items"] if i["key"] == "linkedin:111")
    item.update(status="failed", attempts=3)
    reqs = [
        ("1.json", "", {"type": "retry", "payload": {"keys": ["linkedin:111"]}}),
        ("2.json", "", {"type": "remove", "payload": {"keys": ["linkedin:333"]}}),
        ("3.json", "", {"type": "pause", "payload": {}}),
        ("4.json", "", {"type": "settings", "payload": {"auto": {"enabled": True, "min_score": 70}, "limit": 3, "offsite": "simplify"}}),
        ("5.json", "", {"type": "answers", "answers": {"notice period?": "30 days"}}),
        ("6.json", "", {"type": "notes", "payload": {"linkedin:111": {"status": "interview", "note": "Mon 10am"}}}),
    ]
    pa.apply_requests(q, reqs, pages, PASS, stub, stub)
    assert item["status"] == "queued" and item["attempts"] == 0
    assert next(i for i in q["items"] if i["key"] == "linkedin:333")["status"] == "removed"
    assert q["paused"] is True
    s = pa.settings_of(q, {})
    assert s["auto"]["enabled"] is True and s["auto"]["min_score"] == 70 and s["limit"] == 3 and s["offsite"] == "simplify"
    assert s["auto"]["boards"] == ["linkedin", "naukri"]      # default kept when not sent
    assert stub.pending[0]["answer"] == "30 days"
    assert stub.saved == [("note", {"job_id": "linkedin:111", "status": "interview", "note": "Mon 10am"})]


def test_auto_rule_queues_only_strong_matches_once(pages):
    q = {"items": [], "paused": False, "settings": {"auto": {"enabled": True, "min_score": 60, "boards": ["linkedin", "naukri"]}}}
    cfg = {}
    added = pa.auto_enqueue(q, cfg, pages, PASS, pa.settings_of(q, cfg))
    keys = sorted(i["key"] for i in q["items"])
    assert added == 2 and keys == ["linkedin:111", "naukri:5001"]      # 333 scores 40, 5002 scores 30, seek is "web"
    assert all(i["source"]["auto"] for i in q["items"])
    assert pa.auto_enqueue(q, cfg, pages, PASS, pa.settings_of(q, cfg)) == 0   # reports remembered


def test_progress_and_ledger_sync():
    class Ledger:
        entries = {"linkedin:1": {"status": "applied", "note": "", "at": "2026-09-17T10:00:00"},
                   "5001": {"status": "questionnaire-pending", "note": "asked", "at": "2026-09-17T10:05:00"}}
    q = {"items": [
        {"key": "linkedin:1", "board": "linkedin", "job_id": "1", "status": "queued"},
        {"key": "naukri:5001", "board": "naukri", "job_id": "5001", "status": "queued"},
        {"key": "linkedin:2", "board": "linkedin", "job_id": "2", "status": "queued"},
        {"key": "web:abc", "board": "web", "job_id": "abc", "status": "manual"},
        {"key": "linkedin:9", "board": "linkedin", "job_id": "9", "status": "removed"},
    ]}
    pa.sync_from_ledger(q, Ledger())
    assert q["items"][0]["status"] == "applied"
    assert q["items"][1]["status"] == "questionnaire-pending" and q["items"][1]["note"] == "asked"
    p = pa.progress_of(q)
    assert p == {"total": 4, "applied": 1, "waiting": 1, "manual": 1, "skipped": 0, "failed": 0, "queued": 1, "done": 3, "pct": 75}
