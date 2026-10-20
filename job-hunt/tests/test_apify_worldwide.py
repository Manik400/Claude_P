"""Apify LinkedIn: one worldwide pass per keyword, tagged so the reports can filter on it."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from jobbot.models import Job  # noqa: E402
from jobbot.render import build_payload  # noqa: E402
from jobbot.sources import apify as A  # noqa: E402


class Ctx:
    window_hours = 12
    max_per_source = 60

    def keywords(self):
        return ["software engineer"]

    def country_meta(self, c):
        return {}


def test_worldwide_pass_payload_and_tags(monkeypatch):
    calls = []
    monkeypatch.setattr(A, "_run", lambda ctx, actor, payload, name: (calls.append(payload), [
        {"id": "1", "title": "Software Engineer", "companyName": "Acme", "location": "Berlin, Germany"},
        {"id": "2", "title": "SDE", "companyName": "Foo", "location": "Remote"},
    ])[1])
    jobs = A.ApifyLinkedIn().search_worldwide(Ctx())
    assert calls == [{"keywords": "software engineer", "location": "Worldwide", "datePosted": "past24Hours",
                      "scrapeCompany": False, "limitPerSource": 25}]
    assert [(j.country, j.extra["via"], j.extra["worldwide"]) for j in jobs] == [("DE", "apify", True), ("REMOTE", "apify", True)]


def test_no_per_country_calls_by_default(monkeypatch):
    monkeypatch.delenv("APIFY_LINKEDIN_PER_COUNTRY", raising=False)
    src = A.ApifyLinkedIn()
    assert src.always_worldwide and not src.applies_to("IN")
    monkeypatch.setenv("APIFY_LINKEDIN_PER_COUNTRY", "1")
    assert src.applies_to("IN")


def test_linkedin_is_on_by_default(monkeypatch):
    monkeypatch.delenv("APIFY_SOURCES", raising=False)
    assert A._enabled_sources() == {"naukri", "indeed", "linkedin"}


def test_report_gets_tabs_for_countries_only_the_worldwide_pass_found():
    def job(cc):
        return Job(title="SDE", company="X", url=f"https://x/{cc}", source="apify-linkedin",
                   source_name="LinkedIn (Apify)", country=cc)
    payload = build_payload({"countries": ["IN"], "roles": ["sde"]}, [job("IN"), job("US"), job("US"), job("??")], [])
    assert [c["code"] for c in payload["countries"]] == ["IN", "US", "??"]
    assert payload["countries"][-1]["name"] == "Other / not stated"
