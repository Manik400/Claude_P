"""naukri/jobs/tracker.py - one memory of what is done with, and the sheet rows it writes."""
import json

import pytest

from naukri.jobs import tracker


@pytest.fixture
def store(tmp_path, monkeypatch):
    paths = {
        "LEDGER_PATH": tmp_path / "ledger.json",
        "APPLICATIONS_PATH": tmp_path / "applications.jsonl",
        "NOTES_PATH": tmp_path / "application_notes.json",
        "REJECTED_PATH": tmp_path / "rejected.json",
        "SHEET_CACHE": tmp_path / "tracker_sheet.json",
        "TAILORED_DIR": tmp_path / "tailored",
        "RUNS_DIR": tmp_path / "runs",
    }
    for name, p in paths.items():
        monkeypatch.setattr(tracker, name, p)
    monkeypatch.setattr(tracker, "_match_title_setting", lambda: True)
    tracker.Memory.forget_shared()
    yield paths
    tracker.Memory.forget_shared()


def test_applied_in_ledger_matches_by_id_link_and_title(store):
    store["LEDGER_PATH"].write_text(json.dumps({
        "250925500123": {"title": "SDE 1", "company": "Acme Corp", "status": "applied", "at": "2026-10-09T10:00:00",
                         "url": "https://www.naukri.com/job-listings-sde-1-acme-corp-bengaluru-0-to-2-years-250925500123?src=jobsearchDesk"},
        "linkedin:4300000001": {"title": "Backend Engineer", "company": "Beta", "status": "applied", "at": "2026-10-09T11:00:00",
                                "url": "https://www.linkedin.com/jobs/view/4300000001/?trk=x"},
        "999": {"title": "QA", "company": "Gamma", "status": "skipped", "at": "2026-10-09", "url": "https://x/1"},
    }), encoding="utf-8")
    mem = tracker.Memory.shared()
    # same Naukri id, written with the prefix
    assert mem.blocked(key="naukri:250925500123")
    # same posting by link with different tracking parameters
    assert mem.blocked(url="https://www.naukri.com/job-listings-sde-1-acme-corp-bengaluru-0-to-2-years-250925500123?src=other&sid=1")
    # LinkedIn id read from a differently spelled link
    assert mem.blocked(url="https://in.linkedin.com/jobs/view/backend-engineer-at-beta-4300000001?refId=abc")
    # the same opening on another board: same title at the same company
    why = mem.blocked(url="https://jobs.lever.co/acme/123", company="ACME Corp.", title="SDE-1")
    assert why and "same title" in why
    # skipped is not applied
    assert not mem.blocked(key="999")
    assert not mem.blocked(url="https://jobs.lever.co/acme/999", company="Acme Corp", title="Staff Engineer")


def test_rejected_and_phone_notes_block(store):
    tracker.reject([{"url": "https://boards.greenhouse.io/foo/jobs/42", "company": "Foo", "title": "Software Engineer"}],
                   "removed from the phone")
    store["NOTES_PATH"].write_text(json.dumps({"linkedin:4300000777": {"status": "", "hidden": True, "updated": "2026-10-11T09:00:00"},
                                               "888": {"status": "interview", "updated": "2026-10-11T09:00:00"}}), encoding="utf-8")
    mem = tracker.Memory.shared()
    assert "removed" in mem.blocked(url="https://boards.greenhouse.io/foo/jobs/42?gh_src=abc")
    assert mem.blocked(url="https://www.linkedin.com/jobs/view/4300000777/")
    assert "interview" in mem.blocked(key="naukri:888")
    # a second reject of the same link is not written twice
    assert tracker.reject([{"url": "https://boards.greenhouse.io/foo/jobs/42"}], "again") == 0


def test_sheet_rows_count_and_status_column_decides(store):
    store["SHEET_CACHE"].write_text(json.dumps({"rows": [
        {"Date time": "2026-10-10 12:00", "Job link": "https://careers.x.com/j/1", "Title": "SWE", "Company": "X", "Status": "applied", "Applied by": "manual"},
        {"Date time": "2026-10-10 12:05", "Job link": "https://careers.y.com/j/2", "Title": "SWE", "Company": "Y", "Status": "rejected"},
        {"Date time": "", "Job link": "", "Title": "", "Company": ""},
    ]}), encoding="utf-8")
    mem = tracker.Memory.shared()
    assert "manual" in mem.blocked(url="https://careers.x.com/j/1")
    assert "rejected" in mem.blocked(url="https://careers.y.com/j/2/")
    assert mem.counts["sheet"] == 2


def test_application_rows_for_the_sheet(store):
    store["TAILORED_DIR"].mkdir()
    (store["TAILORED_DIR"] / "20261010-acme-software-engineer.pdf").write_bytes(b"%PDF")
    lines = [
        {"at": "2026-10-10T14:00:00", "board": "company site", "job_id": "web:abc", "title": "Software Engineer", "company": "Acme",
         "url": "https://jobs.acme.com/1", "status": "applied", "note": "3 field(s) filled and submitted · tailored resume, 80% of the job's skills",
         "dry_run": False, "project": "jobhunt"},
        {"at": "2026-10-10T14:05:00", "board": "linkedin", "job_id": "linkedin:1", "title": "SDE", "company": "Beta",
         "url": "https://www.linkedin.com/jobs/view/1/", "status": "applied", "note": "Easy Apply", "dry_run": False, "project": "naukri"},
        {"at": "2026-10-10T14:06:00", "board": "naukri", "job_id": "2", "title": "SDE", "company": "Gamma", "url": "https://naukri.com/x-2",
         "status": "applied", "note": "", "dry_run": True, "project": "naukri"},
        {"at": "2026-10-10T14:07:00", "board": "naukri", "job_id": "3", "title": "SDE", "company": "Delta", "url": "https://naukri.com/x-3",
         "status": "offsite", "note": "", "dry_run": False, "project": "naukri"},
    ]
    store["APPLICATIONS_PATH"].write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    rows, ids = tracker.application_rows(set())
    assert len(rows) == 2 and len(ids) == 2            # dry runs and non-applied outcomes stay off the sheet
    first = dict(zip(tracker.HEADER, rows[0]))
    assert first["Job link"] == "https://jobs.acme.com/1"
    assert first["Resume sent"] == "tailored PDF: 20261010-acme-software-engineer.pdf"
    assert first["Match %"] == "80"
    assert first["Applied by"] == "auto (jobhunt)"
    assert first["Key"] == "web:abc"
    second = dict(zip(tracker.HEADER, rows[1]))
    assert second["Resume sent"] == "LinkedIn profile resume"
    # already-pushed rows are not written again
    rows2, _ = tracker.application_rows(set(ids))
    assert rows2 == []


def test_sync_without_a_sheet_is_quiet(store, monkeypatch):
    monkeypatch.setattr(tracker, "sheet_settings", lambda config=None: {"worksheet": "Applications"})
    out = tracker.sync_sheet({})
    assert out["pushed"] == 0 and "no tracker_sheet" in out["note"]


def test_norm_url_and_keys():
    assert tracker.norm_url("https://www.linkedin.com/jobs/view/123/?trk=a&refId=b#x") == "linkedin.com/jobs/view/123"
    assert tracker.keys_from_url("https://www.linkedin.com/jobs/view/software-engineer-at-x-4300000001?position=1") == ["linkedin:4300000001"]
    assert tracker.keys_from_url("https://www.naukri.com/job-listings-sde-acme-250925500123?src=a") == ["250925500123"]
    assert tracker.norm_key("naukri:5") == "5" and tracker.norm_key("LinkedIn:5") == "linkedin:5"
