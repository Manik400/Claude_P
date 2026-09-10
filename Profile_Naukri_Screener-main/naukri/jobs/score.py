"""Score a job against the profile, 0-100.

The score exists to make one decision: apply now, queue for you to read, or
drop. So it is deliberately blunt and inspectable - every job carries the
breakdown that produced its number, and the daily report prints it. When the
agent applies to something you would not have, the reason is in the report
rather than buried in a model you cannot interrogate.

    skills       0-45   how much of what the job asks for you actually have
    title        0-25   is this the kind of role you want
    experience   0-15   are you inside the band they asked for
    location     0-10   is it somewhere you would work
    freshness    0-5    recent postings get replies; month-old ones do not

Hard rejects (score forced to 0) come first: they encode "never, regardless of
how well the rest matches".
"""
from __future__ import annotations

import re

from naukri import roles

# Different spellings of the same thing, folded together before comparison.
# They come from the active role pack, because which spellings mean the same
# job is a fact about a field: "SDET" folding to "software development engineer
# in test" is right for a tester and meaningless to a SOC analyst, who needs
# "VAPT" to fold instead. See roles/*.yaml and docs/ROLES.md.
SYNONYMS = roles.load()["synonyms"]

# Title words that mark a role as a step sideways or down, used for the title
# component only - a senior title in the body of a junior posting is noise.
SENIORITY_BONUS = ("lead", "senior", "sr", "principal", "staff", "architect", "manager")


def _norm(text: str) -> str:
    text = (text or "").lower()
    for term, replacement in SYNONYMS.items():
        text = re.sub(rf"\b{re.escape(term)}\b", replacement, text)
    return re.sub(r"[^a-z0-9 ]+", " ", text)


def _tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 1}


def _skill_key(skill: str) -> str:
    return " ".join(_norm(skill).split())


def hard_reject(job, config: dict) -> str | None:
    """Return a reason to drop the job outright, or None to keep scoring."""
    title_l = (job.title or "").lower()
    company_l = (job.company or "").lower()

    for blocked in config.get("exclude_companies") or []:
        if blocked.lower().strip() and blocked.lower().strip() in company_l:
            return f"company excluded ({blocked})"

    for word in config.get("exclude_title_keywords") or []:
        if word.lower().strip() and word.lower().strip() in title_l:
            return f"title contains '{word}'"

    must_have = config.get("must_have_any") or []
    if must_have:
        haystack = _norm(" ".join([job.title, " ".join(job.skills), job.description]))
        if not any(_skill_key(term) in haystack for term in must_have if term.strip()):
            return "matches none of must_have_any"

    years = config.get("profile_years")
    gap = config.get("max_experience_gap_years", 2.0)
    if years is not None and job.min_exp is not None and job.min_exp - years > gap:
        return f"needs {job.min_exp:g}y, you have {years:g}y"

    return None


def _skill_score(job, config: dict) -> tuple[float, list[str]]:
    """Fraction of the job's asks that the profile covers, scaled to 45."""
    wanted = [s for s in job.skills if s.strip()]
    if not wanted:
        return 18.0, []  # no stated skills: neutral, neither reward nor punish

    have = {_skill_key(s) for s in config["profile_skills"]}
    # profile_evidence is the whole profile, not just the headline - a job
    # asking for Jenkins was matching nothing, though four years of it sit in
    # the employment history. profile_text is the fallback for callers that
    # build a config by hand and never set the wider key.
    have_blob = " ".join(have) + " " + _norm(config.get("profile_evidence") or config.get("profile_text", ""))

    matched = []
    for skill in wanted:
        key = _skill_key(skill)
        if not key:
            continue
        # Exact skill match, or the skill named anywhere in the profile text.
        if key in have or re.search(rf"\b{re.escape(key)}\b", have_blob):
            matched.append(skill)

    ratio = len(matched) / len(wanted)
    # A job asking for 3 things you all have is weaker evidence than one asking
    # for 10 of which you have 8, so temper the ratio with the absolute count.
    depth = min(len(matched) / 8.0, 1.0)
    return round(45 * (0.65 * ratio + 0.35 * depth), 1), matched


def _title_score(job, config: dict) -> float:
    title_tokens = _tokens(job.title)
    if not title_tokens:
        return 0.0

    targets = [t for t in (config.get("must_have_any") or []) if t.strip()]
    target_tokens: set[str] = set()
    for target in targets:
        target_tokens |= _tokens(target)
    target_tokens |= _tokens(config.get("profile_text", ""))

    overlap = len(title_tokens & target_tokens) / len(title_tokens)
    score = 20 * overlap
    if any(word in title_tokens for word in SENIORITY_BONUS):
        score += 5
    return round(min(score, 25.0), 1)


def _experience_score(job, config: dict) -> float:
    years = config.get("profile_years")
    if years is None or job.min_exp is None:
        return 9.0  # unknown on either side: mid-band rather than a guess
    top = job.max_exp if job.max_exp is not None else job.min_exp + 3
    if job.min_exp <= years <= top:
        return 15.0
    if years < job.min_exp:
        # Under-qualified is the harder no.
        return round(max(0.0, 15 - (job.min_exp - years) * 6), 1)
    # Over-qualified still gets interviews, so penalise gently.
    return round(max(0.0, 15 - (years - top) * 2.5), 1)


def _location_score(job, config: dict) -> float:
    text = (job.location or "").lower()
    if not text:
        return 5.0
    if "remote" in text:
        return 10.0
    for preferred in config.get("preferred_locations") or []:
        if preferred.lower().strip() and preferred.lower().strip() in text:
            return 10.0
    return 2.0


def _freshness_score(job) -> float:
    age = job.age_days
    if age is None:
        return 2.5
    if age <= 2:
        return 5.0
    if age <= 7:
        return 3.0
    if age <= 30:
        return 1.0
    return 0.0


def score(job, config: dict) -> dict:
    """Attach `.score` and `.score_breakdown` to the job; return the breakdown."""
    reason = hard_reject(job, config)
    if reason:
        job.score = 0.0
        job.score_breakdown = {"rejected": reason}
        job.matched_skills = []
        return job.score_breakdown

    skills, matched = _skill_score(job, config)
    breakdown = {
        "skills": skills,
        "title": _title_score(job, config),
        "experience": _experience_score(job, config),
        "location": _location_score(job, config),
        "freshness": _freshness_score(job),
    }
    job.score = round(sum(breakdown.values()), 1)
    job.score_breakdown = breakdown
    job.matched_skills = matched
    return breakdown


def explain(job) -> str:
    """One-line justification, for the daily report."""
    breakdown = getattr(job, "score_breakdown", None) or {}
    if "rejected" in breakdown:
        return f"rejected: {breakdown['rejected']}"
    parts = " ".join(f"{k}={v:g}" for k, v in breakdown.items())
    matched = getattr(job, "matched_skills", [])
    tail = f" | matched: {', '.join(matched[:6])}" if matched else ""
    return f"{parts}{tail}"
