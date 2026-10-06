"""data/index.json on gh-pages: two publishers at once must not lose each other's reports,
and a report file left on the branch without an index entry comes back by itself.

Run from site/:  python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import pages_git  # noqa: E402
import publish  # noqa: E402


def _item(kind, stamp, slug, when, **meta):
    rid = "%s-%s-%s" % (kind, stamp, slug)
    return {"id": rid, "kind": kind, "title": slug, "when": when, "file": "data/%s/%s.%s" % (kind, rid, "json" if kind == "careers" else "html"),
            "bytes": 1, "meta": meta}


def _touch(root, rel, text="x"):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def test_merge_keeps_both_sides_reports(tmp_path):
    root = str(tmp_path)
    pc = _item("naukri", "20261006-072326", "scan", "2026-10-06T07:23:26Z")
    gh = _item("careers", "20261006-121839", "swe", "2026-10-06T12:18:39Z", jobs="841")
    both = _item("jobhunt", "20261005-120000", "old", "2026-10-05T12:00:00Z")
    for it in (pc, gh, both):
        _touch(root, it["file"])
    ours = json.dumps({"updated": "2026-10-06T12:30:00Z", "items": [gh, both]})
    theirs = json.dumps({"updated": "2026-10-06T12:20:00Z", "items": [pc, both], "hidden": [["naukri", "gone"]]})
    out = json.loads(pages_git.merge_index_texts(ours, theirs, root))
    assert [i["id"] for i in out["items"]] == [gh["id"], pc["id"], both["id"]]   # union, newest first
    assert out["updated"] == "2026-10-06T12:30:00Z"
    assert out["hidden"] == [["naukri", "gone"]]


def test_merge_does_not_bring_back_a_report_whose_file_is_gone(tmp_path):
    root = str(tmp_path)
    kept = _item("careers", "20261006-121839", "swe", "2026-10-06T12:18:39Z")
    removed = _item("jobhunt", "20261005-120000", "old", "2026-10-05T12:00:00Z")
    _touch(root, kept["file"])                       # `removed` has no file: deleted from the phone meanwhile
    out = json.loads(pages_git.merge_index_texts(json.dumps({"items": [kept]}), json.dumps({"items": [kept, removed]}), root))
    assert [i["id"] for i in out["items"]] == [kept["id"]]


def test_reconcile_relists_an_orphaned_careers_report_from_its_file(tmp_path):
    pages = str(tmp_path)
    report = {"meta": {"roles": ["software engineer", "SDE"], "countries": ["*"], "relocation": "visa", "experience": "0-2",
                       "days": 1, "hours": None, "list": {"sha": "abc123def456", "count": 8951}},
              "jobs": [{"id": "1", "reloc": "yes"}, {"id": "2", "reloc": "no"}]}
    _touch(pages, "data/careers/careers-20261006-121839-software-engineer-software-developer-bac.json", json.dumps(report))
    listed = _item("careers", "20261006-112537", "earlier", "2026-10-06T11:25:37Z")
    _touch(pages, listed["file"])
    idx = {"updated": None, "items": [listed]}
    added, deleted = publish.reconcile_index(pages, idx)
    assert (added, deleted) == (1, 0)
    new = [i for i in idx["items"] if i["id"].startswith("careers-20261006-121839")][0]
    assert new["title"] == "software engineer, SDE" and new["when"] == "2026-10-06T12:18:39Z"
    assert new["meta"]["jobs"] == "2" and new["meta"]["relocation"] == "1" and new["meta"]["countries"] == "worldwide"
    assert new["meta"]["list_sha"] == "abc123def456" and new["meta"]["list_count"] == "8951"
    # a second pass changes nothing
    assert publish.reconcile_index(pages, idx) == (0, 0)


def test_reconcile_uses_the_html_title_and_the_jobs_file_and_respects_hidden(tmp_path):
    pages = str(tmp_path)
    rid = "jobhunt-20261006-163111-software-engineer"
    _touch(pages, "data/jobhunt/%s.html" % rid, "<html><head><title>Job Hunt · software engineer, SDE · 06 Oct 2026</title></head></html>")
    _touch(pages, "data/jobhunt/%s.jobs.json" % rid, json.dumps([{"id": 1}, {"id": 2}, {"id": 3}]))
    _touch(pages, "data/naukri/naukri-20261006-072326-naukri-openings-2026-10-06-run-1.html", "<title>Naukri openings 2026-10-06 run 1 - Last 24h</title>")
    idx = {"items": [], "hidden": [["naukri", "Naukri openings 2026-10-06 run 1 - Last 24h"]]}
    added, _ = publish.reconcile_index(pages, idx)
    assert added == 1
    it = idx["items"][0]
    assert it["title"] == "software engineer, SDE" and it["meta"]["jobs_file"].endswith(".jobs.json") and it["meta"]["jobs"] == "3"


def test_reconcile_deletes_leftovers_of_one_copy_kinds(tmp_path):
    pages = str(tmp_path)
    live = _item("applications", "20261006-161515", "applications-sent", "2026-10-06T16:15:15Z")
    _touch(pages, live["file"])
    _touch(pages, "data/applications/applications-20261005-005659-applications-sent.html")
    idx = {"items": [live]}
    assert publish.reconcile_index(pages, idx) == (0, 1)
    assert sorted(os.listdir(os.path.join(pages, "data", "applications"))) == [os.path.basename(live["file"])]


def test_prune_keep_trims_each_kind_to_its_limit(tmp_path):
    pages = str(tmp_path)
    items = [_item("careers", "2026100%d-120000" % d, "r", "2026-10-0%dT12:00:00Z" % d) for d in range(1, 8)]
    for it in items:
        _touch(pages, it["file"])
    idx = {"items": list(items)}
    publish.KEEP["careers"], old = 3, publish.KEEP["careers"]
    try:
        gone = publish.prune_keep(pages, idx)
    finally:
        publish.KEEP["careers"] = old
    assert gone == 4 and sorted(i["when"][8:10] for i in idx["items"]) == ["05", "06", "07"]   # save_index sorts
    assert not os.path.exists(os.path.join(pages, items[0]["file"].replace("/", os.sep)))
