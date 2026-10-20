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
    class World(Ctx):
        worldwide = True

    class Chosen(Ctx):
        worldwide = False
        countries = ["IN", "DE", "NL", "REMOTE"]

    class NoRemote(Chosen):
        countries = ["IN", "NL", "AU"]

    assert [j.country for j in A.ApifyLinkedIn().search_worldwide(Chosen())] == ["DE", "REMOTE"]
    assert A.ApifyLinkedIn().search_worldwide(NoRemote()) == []
    calls.clear()
    jobs = A.ApifyLinkedIn().search_worldwide(World())
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


def test_few_countries_ask_those_countries_not_the_world(monkeypatch):
    from jobbot import search as S
    monkeypatch.setenv("APIFY_TOKEN", "x")
    seen = []

    class Src(A.ApifyLinkedIn):
        def search(self, ctx, cc):
            seen.append(cc)
            return []

        def search_worldwide(self, ctx):
            seen.append("WORLD")
            return []

    class Ctx2(Ctx):
        countries = ["DE", "AU", "REMOTE"]
        worldwide = False

    S.run_search(Ctx2(), [Src()], log=lambda *_: None, workers=1)
    assert sorted(seen) == ["AU", "DE"]
    seen.clear()
    Ctx2.countries = ["IN", "DE", "NL", "AU"]
    S.run_search(Ctx2(), [Src()], log=lambda *_: None, workers=1)
    assert seen == ["WORLD"]


def test_relocation_filter_keeps_relocation_and_visa():
    from jobbot.search import relocation_filter
    jobs = [Job(title="SDE", company="A", url="u1", source="x", source_name="X", country="DE",
                description="We offer relocation support to Berlin for you and your family."),
            Job(title="SDE", company="B", url="u2", source="x", source_name="X", country="DE",
                description="We sponsor your visa and work permit."),
            Job(title="SDE", company="C", url="u3", source="x", source_name="X", country="DE",
                description="Hybrid role in Munich. Great coffee.")]
    kept, dropped = relocation_filter(jobs, "visa", log=lambda *_: None)
    assert [j.company for j in kept] == ["A", "B"] and dropped == 1
    kept, _ = relocation_filter(jobs, "strict", log=lambda *_: None)
    assert [j.company for j in kept] == ["A"]
    assert relocation_filter(jobs, "any", log=lambda *_: None) == (jobs, 0)
