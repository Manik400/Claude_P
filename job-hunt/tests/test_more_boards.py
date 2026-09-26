"""Personio, Breezy and BambooHR boards: links resolve, feeds parse, and an unknown tenant
(which these hosts answer with a redirect to their own home page) is a miss, not a board.
Nothing here touches the network."""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from jobbot.careers import ats, resolve  # noqa: E402
from jobbot.careers.companies import Company  # noqa: E402

PERSONIO_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
    <id>1834171</id>
    <subcompany>Acme SE &amp; Co. KG</subcompany>
    <office>Munich</office>
    <additionalOffices><office>Berlin</office></additionalOffices>
    <department>Product and Tech</department>
    <name>Software Engineer, Data Platform</name>
    <jobDescriptions>
        <jobDescription><name>Your role</name><value>&lt;p&gt;Build Python services&lt;/p&gt;</value></jobDescription>
    </jobDescriptions>
    <employmentType>permanent</employmentType>
    <schedule>full-time</schedule>
    <seniority>entry-level</seniority>
    <yearsOfExperience>0-2</yearsOfExperience>
    <createdAt>2026-09-20T14:10:41+00:00</createdAt>
</position>
<position><id>2</id><office>Munich</office><name>Office Manager</name></position>
</workzag-jobs>"""

BREEZY = [{"id": "98", "name": "Backend Developer", "url": "https://acme.breezy.hr/p/98-backend-developer",
           "published_date": "2026-09-20T14:37:22.684Z", "type": {"name": "Full-Time"}, "department": "Tech",
           "location": {"country": {"id": "NL", "name": "Netherlands"}, "city": "Amsterdam",
                        "is_remote": False, "name": "Amsterdam, NL"}}]

BAMBOO = {"meta": {"totalCount": 2}, "result": [
    {"id": "83", "jobOpeningName": "Junior Software Engineer ", "departmentLabel": "Engineering",
     "employmentStatusLabel": "Full-Time", "location": {"city": "Berlin", "state": None},
     "atsLocation": {"country": "Germany", "city": "Berlin"}, "isRemote": None, "locationType": "0"},
    {"id": "84", "jobOpeningName": "Senior Coach", "location": {}, "atsLocation": {}}]}


class Resp:
    def __init__(self, status=200, body=b"", ctype="application/json"):
        self.status_code, self.content, self.headers = status, body, {"content-type": ctype}
        self.text = body.decode("utf-8") if isinstance(body, bytes) else body

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeHttp:
    """Answers by URL prefix; anything unknown is the host's redirect to its home page."""

    def __init__(self, routes):
        self.routes = routes

    def get(self, url, params=None, headers=None, **kw):
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        return Resp(301, b"", "text/html")

    def get_json(self, url, params=None, headers=None, **kw):
        r = self.get(url)
        r.raise_for_status()
        return r.json()


HTTP = FakeHttp({
    "https://acme.jobs.personio.de/xml": Resp(200, PERSONIO_XML, "text/xml; charset=UTF-8"),
    "https://acme.breezy.hr/json": Resp(200, json.dumps(BREEZY).encode()),
    "https://acme.bamboohr.com/careers/list": Resp(200, json.dumps(BAMBOO).encode()),
    "https://acme.bamboohr.com/careers/83/detail": Resp(200, json.dumps(
        {"result": {"jobOpening": {"description": "<p>Python and SQL</p>"}}}).encode()),
})


def everything(title):
    return True


@pytest.mark.parametrize("url, want", [
    ("https://acme.jobs.personio.de/job/1834171", ("personio", "acme")),
    ("https://acme.jobs.personio.com", ("personio", "acme")),
    ("https://acme.breezy.hr/p/98-backend", ("breezy", "acme")),
    ("https://acme.bamboohr.com/careers/83", ("bamboohr", "acme")),
])
def test_links_name_the_board(url, want):
    assert resolve.from_url(url) == want


def test_personio_feed():
    jobs, total, _ = ats.fetch(HTTP, Company("Acme", "personio", "acme"), everything, [""])
    assert total == 2 and len(jobs) == 2
    j = jobs[0]
    assert j.title == "Software Engineer, Data Platform"
    assert j.url == "https://acme.jobs.personio.de/job/1834171"
    assert j.country == "DE" and "Build Python services" in j.description and "0-2" in j.description
    assert resolve.verify(HTTP, "personio", "acme") == 2
    assert resolve.owner(HTTP, "personio", "acme") == "Acme SE & Co. KG"


def test_breezy_feed():
    jobs, total, _ = ats.fetch(HTTP, Company("Acme", "breezy", "acme"), everything, [""])
    assert total == 1 and jobs[0].country == "NL" and jobs[0].url.endswith("98-backend-developer")
    assert resolve.verify(HTTP, "breezy", "acme") == 1


def test_bamboohr_feed_keeps_only_wanted_titles_and_reads_details():
    jobs, total, _ = ats.fetch(HTTP, Company("Acme", "bamboohr", "acme"), lambda t: "Engineer" in t, [""])
    assert total == 2 and len(jobs) == 1
    assert jobs[0].url == "https://acme.bamboohr.com/careers/83" and "Python and SQL" in jobs[0].description
    assert resolve.verify(HTTP, "bamboohr", "acme") == 2


@pytest.mark.parametrize("kind", ["personio", "bamboohr"])
def test_unknown_tenant_is_a_miss(kind):
    # personio.com / bamboohr.com send unknown tenants to their marketing site
    assert resolve.verify(HTTP, kind, "nobody") is None
    with pytest.raises(Exception):
        ats.fetch(HTTP, Company("Nobody", kind, "nobody"), everything, [""])


def test_board_urls():
    assert Company("A", "personio", "acme").careers == "https://acme.jobs.personio.de"
    assert Company("A", "breezy", "acme").careers == "https://acme.breezy.hr"
    assert Company("A", "bamboohr", "acme").careers == "https://acme.bamboohr.com/careers"
