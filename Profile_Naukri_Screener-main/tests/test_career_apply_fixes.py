"""The company-site applier's detection rules, on the cases that failed in the field.

Run: python -m pytest tests/ -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import career_apply as ca  # noqa: E402


@pytest.mark.parametrize("text", [
    "Reject all", "Decline", "Only necessary cookies", "ALLE ABLEHNEN", "Alles afwijzen", "Rechazar todo",
    "Tout refuser", "Hylkää kaikki", "Nur notwendige Cookies zulassen", "Alleen noodzakelijke cookies",
])
def test_cookie_banners_are_declined_in_every_language(text):
    assert ca.COOKIE_DECLINE.match(text)


@pytest.mark.parametrize("text", ["Alle akzeptieren", "Accept all", "Alles accepteren", "Einstellungen"])
def test_cookie_accept_is_never_pressed(text):
    assert not ca.COOKIE_DECLINE.match(text)


@pytest.mark.parametrize("text", [
    "Apply & Interview Resources", "How to apply", "Apply tips", "Application process", "Send message", "Send feedback",
])
def test_nav_links_and_widgets_are_not_the_apply_button(text):
    assert ca.NOT_ACTION.search(text)


@pytest.mark.parametrize("text", ["Apply now", "Apply for this job", "Jetzt bewerben", "Submit application", "Solliciteer"])
def test_real_apply_and_submit_texts_pass(text):
    assert not ca.NOT_ACTION.search(text)
    assert ca.APPLY_TEXT.match(text) or ca.SUBMIT_TEXT.match(text)


@pytest.mark.parametrize("url", [
    "https://www.adzuna.de/land/ad/5894193699?se=x", "https://www.adzuna.in/details/589", "https://jooble.org/jdp/1",
    "https://www.arbeitnow.com/jobs/companies/amber/x", "https://remotive.com/remote-jobs/software-dev/x",
])
def test_aggregators_are_never_the_form(url):
    assert ca.aggregator_host(url)


@pytest.mark.parametrize("url", ["https://boards.greenhouse.io/acme/jobs/1", "https://careers.acme.com/apply"])
def test_employers_are_not_aggregators(url):
    assert not ca.aggregator_host(url)


def field(**kw):
    base = {"idx": "0", "tag": "input", "type": "text", "name": "", "id": "", "placeholder": "", "autocomplete": "",
            "label": "", "legend": "", "group": "", "optionLabel": "", "value": "", "checked": False, "required": False,
            "options": [], "selectedText": "", "password": False, "ctx": "", "ctxFields": 99}
    base.update(kw)
    return base


def test_a_search_box_and_an_alert_email_are_not_an_application():
    fields = [field(name="q", placeholder="Job, Unternehmen, Branche"), field(name="w", placeholder="Stadt, Bundesland"),
              field(type="email", label="E-Mail", ctx="job alert", ctxFields=2)]
    assert ca._not_the_form(fields[0]) and ca._not_the_form(fields[1])
    assert not ca.looks_like_application([f for f in fields if not ca._not_the_form(f)])


def test_a_form_with_a_resume_or_name_and_email_is_an_application():
    assert ca.looks_like_application([field(type="file", label="Resume")])
    assert ca.looks_like_application([field(label="First name"), field(type="email", label="Email")])
    assert ca.looks_like_application([field(label="Full name"), field(type="email", label="Email"), field(tag="textarea", label="Why us?")])


def test_a_location_field_is_part_of_the_form():
    assert not ca._not_the_form(field(label="Location", name="location"))
    assert not ca._not_the_form(field(label="Where did you hear about us?", name="source"))


@pytest.mark.parametrize("text", [
    "Thank you for applying!", "Your application has been submitted", "Vielen Dank für Ihre Bewerbung",
    "Bedankt voor je sollicitatie", "Gracias por tu candidatura", "Kiitos hakemuksesta", "You have applied to this job",
])
def test_thank_you_lines(text):
    assert ca.THANKS.search(text)


@pytest.mark.parametrize("text", ["Applied", "Application sent", "You have applied", "Already applied"])
def test_board_applied_button_texts(text):
    assert ca.APPLIED_TEXT.match(text)


@pytest.mark.parametrize("text", ["Apply on company site", "Apply on company website", "Apply externally"])
def test_offsite_button_texts(text):
    assert ca.OFFSITE_TEXT.match(text)


def test_release_failed_releases_fixed_failures_only(tmp_path, monkeypatch):
    from naukri.jobs import ledger as ledger_mod
    path = tmp_path / "ledger.json"
    now = "2026-09-27T10:00:00"
    entries = {
        "web:1": {"url": "https://careers.acme.com/j/1", "status": "offsite", "at": now,
                  "note": ca.TRIED + "no application form or Apply button found on the company page"},
        "web:2": {"url": "https://www.instahyre.com/job-2/", "status": "offsite", "at": now,
                  "note": ca.TRIED + "this board needs its own account"},
        "web:3": {"url": "https://acme.wd5.myworkdayjobs.com/j/3", "status": "offsite", "at": now,
                  "note": ca.TRIED + "acme.wd5.myworkdayjobs.com needs its own account"},
        "web:4": {"url": "https://careers.acme.com/j/4", "status": "offsite", "at": now,
                  "note": ca.TRIED + "the form has a CAPTCHA - apply by hand"},
        "web:5": {"url": "https://careers.acme.com/j/5", "status": "applied", "at": now, "note": ca.TRIED + "3 field(s) filled and submitted"},
        "123": {"url": "https://www.naukri.com/job-listings-x-123", "status": "offsite", "at": now,
                "note": ca.TRIED + "could not press the company-site Apply button"},
        "linkedin:9": {"url": "https://www.linkedin.com/jobs/view/9/", "status": "offsite", "at": "2026-01-01T00:00:00",
                       "note": ca.TRIED + "found no Submit button"},
    }
    path.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(ledger_mod, "LEDGER_PATH", path)
    monkeypatch.setattr(ledger_mod.Ledger.__init__, "__defaults__", (path,))
    monkeypatch.setattr(ca, "saved_logins", lambda: {"instahyre.com"})
    counts = ca.release_failed()
    after = json.loads(path.read_text(encoding="utf-8"))
    assert counts == {"web": 2, "naukri": 1, "linkedin": 0, "kept": 1}
    assert "web:1" not in after and "web:2" not in after          # listed again by the next search
    assert "web:3" in after and "web:4" in after and "web:5" in after   # Workday login, CAPTCHA, applied: kept
    assert after["123"]["note"].startswith("retry requested: ")   # tried again on the career site
    assert after["linkedin:9"]["note"].startswith(ca.TRIED)       # too old
