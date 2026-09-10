"""Search criteria and thresholds, read from jobs.yaml.

Anything absent from jobs.yaml falls back to one of two places, in this order:

  1. the role pack named by `role:` in jobs.yaml - roles/qa-automation.yaml,
     roles/developer.yaml, roles/support.yaml, roles/cybersecurity.yaml - which
     supplies the field's search keywords and its "is this even my field" gate
  2. the live profile in data/profile.json, for anything specific to you

So a working jobs.yaml can be four lines long, and none of it goes stale when
you edit your Naukri profile. See docs/ROLES.md for writing your own pack.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import yaml

from naukri import roles

log = logging.getLogger("naukri.jobs.config")

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "jobs.yaml"
PROFILE_PATH = ROOT / "data" / "profile.json"

DEFAULTS = {
    # Which roles/*.yaml pack supplies the field vocabulary. Empty means the
    # module default (qa-automation), so an old jobs.yaml keeps working.
    "role": "",
    "searches": [],
    "preferred_locations": [],
    "must_have_any": [],
    "exclude_title_keywords": [],
    "exclude_companies": [],
    "min_salary_lpa": None,
    "auto_apply_min_score": 72,
    "review_min_score": 55,
    "daily_target": 50,
    "max_auto_applies": 20,
    # Cap on apply *attempts* per run. max_auto_applies caps successes, which
    # is not the same thing: a run that keeps hitting unanswerable
    # questionnaires never spends its budget and would walk the whole
    # shortlist. None means "no separate attempt cap".
    "max_apply_attempts": None,
    "max_experience_gap_years": 2.0,
    "include_recommended": True,
    # Answering screening questions is off until the drawer has been captured
    # with --jobs-probe and the selectors verified against it.
    "answer_questionnaires": False,
    # Facts no profile field holds. Only ever what you stated yourself.
    "answers": {},
    # Your own question -> answer rules, tried before any built-in logic.
    "answer_rules": [],
    # Years of experience per skill, stated by you. Layered over the profile's
    # IT-skills table, which usually lists only a couple of entries.
    "skill_years": {},
}


class ConfigError(RuntimeError):
    """jobs.yaml exists but cannot be used."""


def load_profile(path: Path = PROFILE_PATH) -> dict:
    if not path.exists():
        raise ConfigError(
            f"No profile at {path}. Run: python main.py --extract"
        )
    profile = json.loads(path.read_text(encoding="utf-8"))
    if not profile.get("key_skills"):
        raise ConfigError(
            "Profile has no key skills - the extract looks broken. "
            "Re-run: python main.py --extract"
        )
    return profile


def profile_years(profile: dict) -> float | None:
    """Total experience in years, parsed from '6 Years 3 Months'."""
    text = profile.get("experience") or ""
    years = re.search(r"(\d+)\s*Year", text, re.IGNORECASE)
    months = re.search(r"(\d+)\s*Month", text, re.IGNORECASE)
    if not years and not months:
        return None
    total = float(years.group(1)) if years else 0.0
    total += (float(months.group(1)) / 12) if months else 0.0
    return round(total, 2)


def profile_skills(profile: dict) -> list[str]:
    """Key skills plus the skill column of the IT-skills table."""
    skills = list(profile.get("key_skills") or [])
    for row in profile.get("it_skills") or []:
        # Rows read "Playwright - 2025 1 Year 3 Months"; take the leading name.
        name = re.split(r"\s+[-\d]", row, maxsplit=1)[0].strip()
        if name:
            skills.append(name)
    seen, out = set(), []
    for skill in skills:
        key = skill.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(skill.strip())
    return out


def load(path: Path = CONFIG_PATH, profile: dict | None = None) -> dict:
    """Merge jobs.yaml over the defaults, filling gaps from the profile."""
    profile = profile if profile is not None else load_profile()

    config = dict(DEFAULTS)
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}")
        if not isinstance(loaded, dict):
            raise ConfigError(f"{path} must be a YAML mapping.")
        unknown = set(loaded) - set(DEFAULTS)
        if unknown:
            log.warning("Ignoring unknown key(s) in jobs.yaml: %s", ", ".join(sorted(unknown)))
        config.update({k: v for k, v in loaded.items() if k in DEFAULTS})

    config["profile_skills"] = profile_skills(profile)
    config["profile_years"] = profile_years(profile)
    config["profile_text"] = " ".join(
        str(profile.get(field) or "")
        for field in ("resume_headline", "profile_summary", "current_designation")
    )
    # Evidence that you have a skill lives in the whole profile, not the
    # headline: Docker, Jenkins and Grafana are named only in employment and
    # projects, so 71 of the 281 stored jobs lost skill points for things you
    # do every day. This is a second key rather than a wider profile_text
    # because score._title_score uses profile_text as its target-token set -
    # widening it in place took that set from 57 to 217 tokens and started
    # paying "AWS Connect Developer" 6.7 title points.
    evidence = []
    for field in ("resume_headline", "profile_summary", "current_designation",
                  "career_profile", "employment", "projects", "it_skills"):
        value = profile.get(field)
        if isinstance(value, list):
            evidence.extend(str(item) for item in value)
        elif value:
            evidence.append(str(value))
    config["profile_evidence"] = " ".join(evidence)

    # The role pack fills anything field-shaped that jobs.yaml left out. Merged
    # after the YAML, never over it: a pack is a starting point, and a person
    # who wrote `must_have_any` in their own file meant it.
    pack = roles.load(config["role"] or None)
    config["role"] = pack["name"]
    config["role_label"] = pack["label"]
    config["primary_role"] = pack["primary_role"]
    for key in ("must_have_any", "exclude_title_keywords"):
        if not config[key]:
            config[key] = list(pack[key])

    if not config["searches"]:
        config["searches"] = list(pack["searches"]) or _default_searches(profile, pack)
    if not config["preferred_locations"]:
        location = (profile.get("location") or "").split(",")[0].strip()
        config["preferred_locations"] = [l for l in (location, "Remote") if l]

    if config["auto_apply_min_score"] < config["review_min_score"]:
        raise ConfigError(
            "auto_apply_min_score must be >= review_min_score "
            f"(got {config['auto_apply_min_score']} and {config['review_min_score']})."
        )
    return config


def _default_searches(profile: dict, pack: dict) -> list[dict]:
    """Search terms inferred from the role pack and profile, as a last resort.

    Only reached when neither jobs.yaml nor the pack lists any searches - the
    four shipped packs all do, so this is the path a hand-written pack takes.

    Breadth beats depth here: several distinct keyword/location pairs return
    more usable jobs than paging deep into one query, and each result page is
    a fresh set of 20 rather than the long tail of a single ranking.
    """
    location = (profile.get("location") or "").split(",")[0].strip() or None
    top_skills = profile_skills(profile)[:4]
    keywords = list(pack["seed_keywords"]) + top_skills
    seen, terms = set(), []
    for keyword in keywords:
        key = keyword.lower()
        if key not in seen:
            seen.add(key)
            terms.append(keyword)
    return [{"keyword": k, "location": location} for k in terms[:5]]
