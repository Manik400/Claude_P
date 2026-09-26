"""Your answers to the questions recruiters ask, edited in the dashboard.

Everything the dashboard's "My answers" form saves lands in
data/jobs/my_answers.yaml and is laid over jobs.yaml on every run:

    facts        expected CTC, phone, relocation, notice buyout - and, if you
                 set them, overrides for what the profile says about notice
                 period, current CTC, total experience and location
    skill_years  years per skill, quoted to recruiters for "how many years
                 of X" questions
    policies     your Yes / No / ask-me position on the standard screening
                 questions (bond, third-party payroll, pay cut, work from
                 office, shifts, travel ...). Each becomes an answer rule
                 ahead of the ones in jobs.yaml.

Free-text answers to specific questions live in the answer bank
(questions.py); the dashboard edits those in the same form.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger("naukri.jobs.my_answers")

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "data" / "jobs" / "my_answers.yaml"

# The standard screening questions, as recognisable patterns. `default` is
# what a fresh form shows: "ask" means the question is left for you.
POLICIES: list[dict] = [
    {"id": "bond", "label": "Service bond / agreement / security deposit",
     "match": r"bond|service agreement|surety|security deposit", "default": "ask"},
    {"id": "contract", "label": "Contract or third-party payroll role",
     "match": r"third.?party payroll|c2h|contract.?to.?hire|contract (role|position|basis)|payroll of|contractual", "default": "ask"},
    {"id": "pay_cut", "label": "Pay cut / lower CTC than current",
     "match": r"pay cut|salary cut|reduction in (ctc|salary)|lower (ctc|salary|package)|unpaid|without (pay|salary)", "default": "no"},
    {"id": "career_gap", "label": "Any gap in education or career",
     "match": r"any gap in (your )?(education|career|employment)|career gap|employment gap", "default": "no"},
    {"id": "wfo", "label": "Work from office (5 days / onsite)",
     "match": r"5 days office|work from office|wfo|return to office|onsite|on-site|in-office", "default": "yes"},
    {"id": "shifts", "label": "Rotational / night shifts",
     "match": r"rotational shift|night shift|shifts?|24x7|24/7", "default": "ask"},
    {"id": "travel", "label": "Willing to travel",
     "match": r"willing to travel|travel(ling)? (required|for)|open to travel", "default": "yes"},
    {"id": "relocate", "label": "Willing to relocate",
     "match": r"(willing|open|ready|ok|okay|comfortable) (to|with) relocat|can you relocat|relocate to", "default": "yes"},
    {"id": "passport", "label": "Valid passport",
     "match": r"valid passport|passport", "default": "yes"},
    {"id": "immediate", "label": "Immediate joiner / join within 15-30 days",
     "match": r"immediate joiner|join immediately|join within|joining within|available immediately", "default": "ask"},
    {"id": "lower_role", "label": "Lower designation / band",
     "match": r"lower (designation|position|title|band)|designation downgrade|step down", "default": "ask"},
    {"id": "background", "label": "Background verification consent",
     "match": r"background (check|verification)|bgv|reference check", "default": "yes"},
    {"id": "laptop", "label": "Own laptop / internet for remote work",
     "match": r"own laptop|personal laptop|internet connection|work from home setup", "default": "yes"},
    {"id": "currently_working", "label": "Currently employed",
     "match": r"currently (working|employed)|are you working", "default": "ask"},
    {"id": "acknowledge", "label": "Mandatory steps (join the company's WhatsApp group, confirm you read the details)",
     "match": r"\b(is|are) (mandatory|compulsory)\b|must join|(please|kindly) (join|confirm)|join (our|the) (whatsapp|telegram)|"
              r"whatsapp group|i have read (and understood|the)",
     "default": "yes"},
]

FACT_FIELDS: list[dict] = [
    {"id": "expected_ctc", "label": "Expected CTC (LPA)", "hint": "e.g. 12 or 12.5", "kind": "text"},
    {"id": "phone", "label": "Mobile number", "hint": "LinkedIn Easy Apply asks for it", "kind": "text"},
    {"id": "willing_to_relocate", "label": "Willing to relocate", "kind": "bool"},
    {"id": "notice_buyout", "label": "Can buy out notice period", "kind": "bool"},
    {"id": "nationality", "label": "Nationality", "hint": "e.g. Indian", "kind": "text"},
    {"id": "notice_period_months", "label": "Notice period (months)", "hint": "blank = from your Naukri profile", "kind": "text", "override": True},
    {"id": "current_ctc_lpa", "label": "Current CTC (LPA)", "hint": "blank = from your Naukri profile", "kind": "text", "override": True},
    {"id": "total_experience_years", "label": "Total experience (years)", "hint": "blank = from your Naukri profile", "kind": "text", "override": True},
    {"id": "current_location", "label": "Current location", "hint": "blank = from your Naukri profile", "kind": "text", "override": True},
]

OVERRIDE_KEYS = ("notice_period_months", "current_ctc_lpa", "total_experience_years", "current_location")
ANSWER_KEYS = ("expected_ctc", "phone", "willing_to_relocate", "notice_buyout", "nationality")


def load() -> dict:
    if not PATH.exists():
        return {"facts": {}, "skill_years": {}, "policies": {}}
    try:
        data = yaml.safe_load(PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        log.error("%s is not valid YAML (%s) - ignored", PATH, exc)
        return {"facts": {}, "skill_years": {}, "policies": {}}
    if not isinstance(data, dict):
        return {"facts": {}, "skill_years": {}, "policies": {}}
    return {
        "facts": dict(data.get("facts") or {}),
        "skill_years": dict(data.get("skill_years") or {}),
        "policies": dict(data.get("policies") or {}),
    }


def save(data: dict) -> Path:
    clean = {
        "facts": {k: v for k, v in (data.get("facts") or {}).items() if v not in (None, "")},
        "skill_years": {},
        "policies": {k: v for k, v in (data.get("policies") or {}).items() if v in ("yes", "no", "ask")},
    }
    for name, years in (data.get("skill_years") or {}).items():
        name = str(name).strip()
        if not name:
            continue
        try:
            clean["skill_years"][name] = float(years)
        except (TypeError, ValueError):
            continue
    PATH.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Written by the dashboard (python main.py --dashboard). Laid over jobs.yaml\n"
              "# on every run: facts and skill years here win; policies become answer\n"
              "# rules ahead of the ones in jobs.yaml.\n")
    PATH.write_text(header + yaml.safe_dump(clean, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return PATH


def _number(value):
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def overlay(config: dict) -> dict:
    """Lay the dashboard's answers over a loaded jobs.yaml config, in place."""
    data = load()
    answers = dict(config.get("answers") or {})
    for key in ANSWER_KEYS:
        value = data["facts"].get(key)
        if value not in (None, ""):
            answers[key] = value
    config["answers"] = answers

    skill_years = dict(config.get("skill_years") or {})
    skill_years.update(data["skill_years"])
    config["skill_years"] = skill_years

    overrides = {}
    for key in OVERRIDE_KEYS:
        value = data["facts"].get(key)
        if value in (None, ""):
            continue
        overrides[key] = value if key == "current_location" else _number(value)
    config["fact_overrides"] = overrides

    rules = []
    for policy in POLICIES:
        choice = data["policies"].get(policy["id"], policy["default"])
        if choice == "yes":
            rules.append({"match": policy["match"], "answer": "Yes", "_policy": policy["id"]})
        elif choice == "no":
            rules.append({"match": policy["match"], "answer": "No", "_policy": policy["id"]})
        elif choice == "ask" and policy["id"] in data["policies"]:
            # An explicit "ask me" must win over a jobs.yaml rule that would
            # otherwise answer it - so it is a skip rule, not an absence.
            rules.append({"match": policy["match"], "skip": True, "_policy": policy["id"]})
    config["answer_rules"] = rules + list(config.get("answer_rules") or [])
    return config


def form_state(profile: dict, config: dict) -> dict:
    """What the dashboard form shows: saved values plus what the profile says."""
    data = load()
    profile_facts = {
        "notice_period_months": profile.get("notice_period") or "",
        "current_ctc_lpa": profile.get("current_salary") or "",
        "total_experience_years": profile.get("experience") or "",
        "current_location": profile.get("location") or "",
    }
    jobs_yaml_answers = {str(k).lower(): v for k, v in (config.get("answers") or {}).items()}
    facts = {}
    for field in FACT_FIELDS:
        key = field["id"]
        saved = data["facts"].get(key)
        facts[key] = {
            "value": "" if saved is None else saved,
            "from_jobs_yaml": jobs_yaml_answers.get(key, ""),
            "from_profile": profile_facts.get(key, ""),
        }
    skill_years = dict(config.get("skill_years") or {})
    skill_years.update(data["skill_years"])
    return {
        "fields": FACT_FIELDS,
        "facts": facts,
        "skill_years": skill_years,
        "profile_skills": list(config.get("profile_skills") or [])[:60],
        "policies": [dict(p, choice=data["policies"].get(p["id"], p["default"])) for p in POLICIES],
        "path": str(PATH),
    }
