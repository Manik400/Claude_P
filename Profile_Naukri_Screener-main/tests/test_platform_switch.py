"""Platform auto-apply is off by default: only company career pages are applied to.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import career_apply, platform_switch  # noqa: E402


@pytest.fixture
def switch(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_switch, "PATH", tmp_path / "platform_apply.json")
    return platform_switch


def test_off_until_switched_on(switch):
    assert switch.stored() is None
    assert not switch.enabled({})
    assert switch.set_enabled(True) and switch.enabled({})
    assert not switch.set_enabled(False) and not switch.enabled({})


def test_the_ui_switch_wins_over_jobs_yaml(switch):
    assert switch.enabled({"platform_apply": True})       # jobs.yaml, while the switch was never set
    switch.set_enabled(False)
    assert not switch.enabled({"platform_apply": True})


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
