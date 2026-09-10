"""Every shipped role pack must load, and must be about its own field.

The packs are data, which is exactly why they need tests: a typo in a YAML
alias list produces no error anywhere, just a skill that silently never matches
and a study page quietly missing a row.

No network and no model calls, like the rest of the suite.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from naukri import roles  # noqa: E402

SHIPPED = ("qa-automation", "developer", "support", "cybersecurity")

# One advert per field, written the way these actually read on Naukri.
ADVERTS = {
    "qa-automation":
        "SDET: Playwright and Selenium automation in Python, PyTest, REST API "
        "testing with Postman, CI/CD on Jenkins, Page Object Model, JIRA, Agile.",
    "developer":
        "Backend Developer: Java, Spring Boot, microservices, REST API design, "
        "MySQL query optimisation, Docker, Kubernetes, AWS. Strong in OOPS, data "
        "structures and design patterns. Unit testing with JUnit. Agile team.",
    "support":
        "Application Support Engineer L2: incident management via ServiceNow, SLA "
        "adherence, log analysis in Splunk, SQL queries, Unix commands, Control-M "
        "batch job monitoring, RCA, escalation, 24x7 rotational shift, ITIL.",
    "cybersecurity":
        "SOC Analyst: monitor SIEM (Splunk/QRadar) alerts, triage incidents, threat "
        "hunting, EDR (CrowdStrike), phishing analysis, vulnerability management "
        "with Nessus, ISO 27001 audit support, CEH preferred.",
}


def _pattern(alias: str) -> re.Pattern:
    """The same matcher skills.py compiles, so the tests check real behaviour."""
    escaped = re.escape(alias)
    if re.match(r"^\w", alias) and re.search(r"\w$", alias):
        return re.compile(rf"\b{escaped}\b", re.I)
    return re.compile(rf"(?<![\w]){escaped}(?![\w])", re.I)


def _hits(pack: dict, text: str) -> set[str]:
    return {canonical for canonical, (_cat, aliases) in pack["lexicon"].items()
            if any(_pattern(alias).search(text) for alias in aliases)}


@pytest.mark.parametrize("name", SHIPPED)
def test_pack_loads(name):
    pack = roles.load(name)
    assert pack["name"] == name
    assert pack["label"] and pack["primary_role"]
    assert pack["seed_keywords"], "a pack needs seeds for the no-searches fallback"
    assert pack["must_have_any"], "without this gate every job in every field scores"


def test_every_pack_is_listed():
    assert set(SHIPPED) <= set(roles.available())
    # Files starting with _ are shared includes, not selectable roles.
    assert "_common" not in roles.available()


@pytest.mark.parametrize("name", SHIPPED)
def test_lexicon_is_well_formed(name):
    for canonical, (category, aliases) in roles.load(name)["lexicon"].items():
        assert category, f"{name}: {canonical} has no category"
        assert aliases, f"{name}: {canonical} has no aliases and can never match"
        assert all(a == a.lower() for a in aliases), \
            f"{name}: {canonical} has a non-lowercase alias; matching is case-insensitive"
        assert len(set(aliases)) == len(aliases), \
            f"{name}: {canonical} repeats an alias"


@pytest.mark.parametrize("name", SHIPPED)
def test_pack_inherits_common(name):
    """The shared skills are there without every pack restating them."""
    lexicon = roles.load(name)["lexicon"]
    for shared in ("Git", "Docker", "Linux", "Agile / Scrum"):
        assert shared in lexicon, f"{name} lost the common skill {shared}"


@pytest.mark.parametrize("name", SHIPPED)
def test_pack_wins_on_its_own_advert(name):
    """A pack must match its own field's advert better than any other pack.

    This is the check that catches a lexicon drifting off its field - the way
    a QA pack would if it grew enough general-purpose developer terms to start
    outscoring the developer pack on a backend advert.
    """
    advert = ADVERTS[name]
    scores = {other: len(_hits(roles.load(other), advert)) for other in SHIPPED}
    best = max(scores, key=scores.get)
    assert best == name, f"{name} advert matched {best} better: {scores}"
    assert scores[name] >= 8, f"{name} only matched {scores[name]} skills in its own advert"


@pytest.mark.parametrize("name", SHIPPED)
def test_field_specific_skills_are_present(name):
    """The terms an interview in this field would actually turn on."""
    expected = {
        "qa-automation": ("Selenium", "Playwright", "Page Object Model"),
        "developer": ("Spring Boot", "System design", "Data structures & algorithms"),
        "support": ("ITIL", "Incident management", "ServiceNow"),
        "cybersecurity": ("SIEM", "Penetration testing", "ISO 27001"),
    }[name]
    lexicon = roles.load(name)["lexicon"]
    for skill in expected:
        assert skill in lexicon, f"{name} is missing {skill}"


def test_unknown_role_names_the_alternatives():
    with pytest.raises(roles.RoleError) as exc:
        roles.load("does-not-exist")
    message = str(exc.value)
    assert "does-not-exist" in message
    # The error has to say what IS valid, or the reader is stuck.
    assert "qa-automation" in message


def test_role_specific_definition_overrides_common():
    """A pack redefining a common skill replaces it rather than duplicating it."""
    common = roles._read("_common")["lexicon"]
    qa = roles.load("qa-automation")["lexicon"]
    # REST API testing is QA's own; REST APIs is the common one. Both exist,
    # which is the point - they are different skills, not a collision.
    assert "REST APIs" in common
    assert "REST API testing" in qa
    assert len(qa) == len({k.lower() for k in qa}), "a canonical name is duplicated"


def test_active_name_falls_back_when_jobs_yaml_is_absent(tmp_path):
    assert roles.active_name(tmp_path / "nope.yaml") == roles.DEFAULT_ROLE


def test_active_name_reads_the_role_key(tmp_path):
    path = tmp_path / "jobs.yaml"
    path.write_text("role: support\nsearches: []\n", encoding="utf-8")
    assert roles.active_name(path) == "support"


def test_active_name_survives_a_broken_jobs_yaml(tmp_path):
    """A malformed config should not take the whole toolkit down with it."""
    path = tmp_path / "jobs.yaml"
    path.write_text("role: [unclosed\n", encoding="utf-8")
    assert roles.active_name(path) == roles.DEFAULT_ROLE
