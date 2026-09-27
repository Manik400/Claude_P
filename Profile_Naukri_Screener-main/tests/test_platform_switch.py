"""Per-platform auto-apply switches: Naukri and LinkedIn off by default, every other platform on;
a platform's switch never touches applications on the employer's own site.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import career_apply, platform_switch  # noqa: E402


@pytest.fixture
def switch(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_switch, "PATH", tmp_path / "platform_apply.json")
    return platform_switch


def test_defaults_naukri_and_linkedin_off_rest_on(switch):
    assert switch.stored() is None
    assert not switch.allowed("naukri", {}) and not switch.allowed("linkedin", {})
    assert switch.allowed("instahyre", {}) and switch.allowed("https://www.hirist.tech/j/2", {})
    assert switch.allowed("https://careers.acme.com/jobs/1", {})     # "other"
    assert switch.enabled({})                                          # some platform is on


def test_one_platform_at_a_time(switch):
    switch.set_enabled({"instahyre": False})
    assert not switch.allowed("https://www.instahyre.com/job-1/")
    assert switch.allowed("wellfound") and not switch.allowed("naukri")
    switch.set_enabled({"naukri": True})
    assert switch.allowed("https://www.naukri.com/job-listings-x-1") and not switch.allowed("instahyre")
    saved = json.loads(switch.PATH.read_text(encoding="utf-8"))["platforms"]
    assert saved["naukri"] is True and saved["instahyre"] is False and saved["linkedin"] is False


def test_all_on_or_all_off(switch):
    assert all(switch.set_enabled(True).values())
    assert switch.allowed("linkedin")
    assert not any(switch.set_enabled(False).values())
    assert not switch.enabled({})
    assert "off everywhere" in switch.summary()


def test_old_one_switch_file_is_read(switch):
    switch.PATH.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert switch.allowed("linkedin")
    switch.PATH.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert not switch.allowed("naukri") and switch.allowed("instahyre")   # the defaults, not "everything off"


def test_jobs_yaml_only_while_the_file_does_not_exist(switch):
    assert switch.allowed("linkedin", {"platform_apply": True})
    switch.set_enabled({"linkedin": False})
    assert not switch.allowed("linkedin", {"platform_apply": True})


def test_platform_of_urls():
    assert platform_switch.platform_of("https://www.seek.com.au/job/4") == "seek"
    assert platform_switch.platform_of("https://th.jobsdb.com/job/5") == "seek"
    assert platform_switch.platform_of("https://in.indeed.com/viewjob?jk=5") == "indeed"
    assert platform_switch.platform_of("https://boards.greenhouse.io/acme/jobs/1") == "other"


def test_off_note_names_the_platform():
    assert "LinkedIn" in platform_switch.off_note("https://www.linkedin.com/jobs/view/1/")


@pytest.mark.parametrize("url", [
    "https://www.naukri.com/job-listings-x-123", "https://www.linkedin.com/jobs/view/1/",
    "https://www.instahyre.com/job-1/", "https://www.hirist.tech/j/2", "https://wellfound.com/jobs/3",
    "https://www.seek.com.au/job/4", "https://in.indeed.com/viewjob?jk=5",
])
def test_job_platforms_are_recognised(url):
    assert career_apply.platform_host(url)
    assert career_apply.platform_host(url, career_apply.APPLY_ON_BOARD)


@pytest.mark.parametrize("url", [
    "https://boards.greenhouse.io/acme/jobs/1", "https://jobs.lever.co/acme/abc",
    "https://careers.acme.com/jobs/42", "https://apply.workable.com/acme/j/ABC/",
])
def test_company_pages_are_not_platforms(url):
    assert career_apply.platform_host(url) is None


def test_boards_that_link_out_are_still_followed():
    url = "https://duunitori.fi/tyopaikat/tyo/x-123"
    assert career_apply.platform_host(url)                                   # no form filled there
    assert career_apply.platform_host(url, career_apply.APPLY_ON_BOARD) is None  # but the posting is opened


def test_a_platform_skip_is_not_recorded_so_it_waits():
    assert career_apply.transient("platform-off", "")
    assert career_apply.queue_status("platform-off") == "queued"
