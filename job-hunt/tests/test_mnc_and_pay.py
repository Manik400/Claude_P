"""jobbot/mnc.py and jobbot/salary_lookup.py - the MNC list, company matching, pay estimates."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from jobbot import mnc, salary_lookup  # noqa: E402


def test_norm_strips_the_legal_and_geographic_tail():
    assert mnc.norm("Amazon Development Centre India Pvt. Ltd.") == "amazon"
    assert mnc.norm("JPMorgan Chase & Co.") == "jpmorgan chase &"  or mnc.norm("JPMorgan Chase & Co.").startswith("jpmorgan chase")
    assert mnc.norm("SAP Labs India") == "sap"
    assert mnc.norm("Zoho") == "zoho"


@pytest.mark.parametrize("name, expect", [
    ("Amazon Development Centre India Pvt Ltd", "Amazon"),
    ("Amazon Web Services", "Amazon"),
    ("Google India Private Limited", "Google"),
    ("Microsoft India (R&D) Pvt Ltd", "Microsoft"),
    ("JPMorgan Chase & Co.", "JPMorgan Chase"),
    ("Goldman Sachs Services", "Goldman Sachs"),
    ("Tata Consultancy Services", "Tata Consultancy Services"),
    ("TCS", "Tata Consultancy Services"),
    ("Flipkart Internet Private Limited", "Flipkart"),
    ("D. E. Shaw India", "D. E. Shaw"),
    ("Samsung R&D Institute India - Bangalore", "Samsung"),
])
def test_known_companies_match(name, expect):
    m = mnc.match(name)
    assert m and m["name"] == expect, (name, m)


def test_unknown_and_near_misses_do_not_match():
    assert mnc.match("Sapient Razorfish") is None or mnc.match("Sapient Razorfish")["name"] != "SAP"   # "sap" only as a whole word
    assert mnc.match("Some Local Startup Pvt Ltd") is None
    assert mnc.match("") is None


def test_typical_pay_and_json():
    lo, hi = mnc.typical_lpa("Google India")
    assert lo >= 15 and hi > lo
    data = json.loads(mnc.as_json())
    assert data["companies"] and data["tiers"]["bigtech"]
    assert any(c["n"] == "Google" for c in data["companies"])


def test_estimate_uses_the_typical_band_without_any_network(tmp_path, monkeypatch):
    monkeypatch.setattr(salary_lookup, "CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setattr(salary_lookup, "_cache", None)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.setattr(salary_lookup, "_load_env", lambda: None)
    est = salary_lookup.estimate("SDE 1", "Amazon Development Centre India")
    assert est and est["kind"] == "typical" and 10 <= est["lpa"] <= 30
    # cached now, and an unknown company without keys stays unknown (cached as None too)
    assert json.load(open(tmp_path / "cache.json", encoding="utf-8"))
    assert salary_lookup.estimate("Developer", "Nobody Knows Pvt Ltd") is None


def test_role_family_and_label():
    assert salary_lookup.role_family("Senior DevOps Engineer") == "devops engineer"
    assert salary_lookup.role_family("SDE-1 Backend") == "backend developer"
    assert salary_lookup.role_family("Member of Technical Staff") == "software engineer"
    assert salary_lookup.label(12.0, "stated") == "₹12 LPA"
    assert salary_lookup.label(12.5, "typical") == "~₹12.5 LPA"


def test_score_bonus_prefers_well_paying_mncs():
    assert salary_lookup.score_bonus({"is_mnc": True, "mnc_tier": "bigtech", "lpa": 22, "lpa_kind": "stated"}) == 16
    assert salary_lookup.score_bonus({"is_mnc": False, "lpa": 4, "lpa_kind": "stated"}) == -10
    assert salary_lookup.score_bonus({}) == 0
