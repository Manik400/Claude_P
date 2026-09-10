"""The gate from §13, run before anything is written.

Every check returns a row rather than raising, because the useful outcome of a
failed check is usually "regenerate these six questions", not "throw the run
away". `report()` produces the rows; `repairable()` turns the fixable ones into
a list of question indices for generate.py to replace.

The check that matters most and is the least obvious is `invented_experience`.
A model told not to fabricate will mostly comply, but "mostly" is the wrong bar
when the failure mode is the candidate repeating a fabricated claim to an
interviewer. So every answer on a Gap skill is scanned for first-person
experience claims, and anything that trips it is flagged for regeneration.
"""
from __future__ import annotations

import re

from . import dedupe

TARGET = {"basic": 30, "intermediate": 40, "advanced": 30}
TOTAL = 100
MIN_ANSWER_CHARS = 180

# First-person claims of having done something. Deliberately narrow: "I would
# use Kubernetes" is a fine answer for a Gap skill, "I have used Kubernetes"
# is not, and the difference is the tense.
CLAIM_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"\bI (?:have|'ve) (?:used|worked|built|written|implemented|automated|deployed|managed|led|owned|configured|maintained|tested)\b",
        r"\bI (?:used|built|wrote|implemented|automated|deployed|managed|led|owned|configured|maintained|created|designed|set up)\b",
        r"\bin my (?:\d+\+? ?years?|experience|role|project|work|current role|previous role)\b",
        r"\bmy (?:\d+\+? ?years?) (?:of |with |in )?\b",
        r"\bwe (?:used|built|implemented|deployed|automated|migrated|ran)\b",
        r"\bat (?:my|our) (?:current|previous|last) (?:company|employer|role|job)\b",
        r"\bI (?:am|'m) (?:currently )?(?:responsible for|the owner of)\b",
        r"\bhaving (?:used|worked with|built)\b",
    )
]

# An answer that names the gap honestly is allowed to sit next to a claim
# pattern - "I have used Selenium Grid, though not Kubernetes" is correct.
HONESTY_MARKERS = [
    re.compile(p, re.I) for p in (
        r"\b(?:have not|haven't|not yet|no hands.?on|never used|not used)\b",
        r"\bwould (?:need to|have to|come up to speed|ramp up|learn)\b",
        r"\b(?:studied|read about|learning|upskilling|self.?taught|conceptually)\b",
        r"\bclosest (?:thing|experience|equivalent)\b",
        r"\bnot (?:something|a tool) I(?:'ve| have)\b",
    )
]


def _has_claim(text: str) -> str | None:
    for pattern in CLAIM_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return None


def _is_honest(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in HONESTY_MARKERS)


def _slug(text: str) -> str:
    """Fold a skill name for comparison: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _row(name: str, ok: bool, detail: str, indices: list[int] | None = None,
         fatal: bool = False) -> dict:
    return {"check": name, "ok": ok, "detail": detail,
            "indices": indices or [], "fatal": fatal}


def report(prep: dict) -> dict:
    """Run every §13 check. Returns {"ok": bool, "checks": [...]}"""
    jobs = prep.get("jobs") or []
    questions = prep.get("questions") or []
    matrix = prep.get("skill_matrix") or []
    checks: list[dict] = []

    # --- structure
    checks.append(_row(
        "exactly 10 JDs analysed", len(jobs) == 10,
        f"{len(jobs)} job description(s)", fatal=True))

    jd_thin = [index + 1 for index, job in enumerate(jobs)
               if len(job.get("jd_text") or "") < 250]
    checks.append(_row(
        "JD text is substantive", not jd_thin,
        "all ten JDs carry usable text" if not jd_thin
        else f"JD{', JD'.join(map(str, jd_thin))} under 250 chars - short postings, "
             f"analysis leans on the tagged skills for those"))

    checks.append(_row(
        "exactly 100 questions", len(questions) == TOTAL,
        f"{len(questions)} question(s)"))

    counts = {level: sum(1 for q in questions if q.get("level") == level)
              for level in TARGET}
    for level, wanted in TARGET.items():
        checks.append(_row(
            f"exactly {wanted} {level}", counts[level] == wanted,
            f"{counts[level]} {level}"))

    # --- per-question quality
    unanswered = [i for i, q in enumerate(questions)
                  if len((q.get("answer") or "").strip()) < MIN_ANSWER_CHARS]
    checks.append(_row(
        "every question has an answer", not unanswered,
        "all answered" if not unanswered
        else f"{len(unanswered)} answer(s) missing or under {MIN_ANSWER_CHARS} chars",
        unanswered))

    unlinked = [i for i, q in enumerate(questions)
                if not [n for n in (q.get("jd_numbers") or []) if 1 <= n <= len(jobs)]]
    checks.append(_row(
        "questions are relevant to the Top 10 JDs", not unlinked,
        "every question maps to at least one JD" if not unlinked
        else f"{len(unlinked)} question(s) cite no valid JD", unlinked))

    unprofiled = [i for i, q in enumerate(questions)
                  if not (q.get("profile_link") or "").strip()]
    checks.append(_row(
        "questions are relevant to the profile", not unprofiled,
        "every question is tied to the resume or named as a study topic"
        if not unprofiled else f"{len(unprofiled)} question(s) carry no profile link",
        unprofiled))

    # --- duplicates
    lexical = dedupe.duplicate_indices(questions)
    checks.append(_row(
        "no duplicate or near-duplicate questions", not lexical,
        "no concept is asked about twice" if not lexical
        else f"{len(lexical)} near-duplicate(s) by concept key", sorted(lexical)))

    flagged = prep.get("semantic_duplicates") or []
    checks.append(_row(
        "semantic duplicate pass ran", prep.get("semantic_pass_ran", False),
        f"{len(flagged)} pair(s) flagged and replaced" if prep.get("semantic_pass_ran")
        else "the semantic pass did not complete - lexical dedupe only"))

    # --- honesty
    # Matched loosely here too, but the direction matters: under-matching lets
    # a fabricated claim through, so a question tagged "Kubernetes operators"
    # must still be checked against the "Kubernetes" gap row.
    gap_skills = {_slug(row["skill"]) for row in matrix if row["status"] == "gap"}
    invented = []
    for index, question in enumerate(questions):
        named = [_slug(question.get("skill"))] + \
                [_slug(s) for s in (question.get("secondary_skills") or [])]
        named = [tag for tag in named if tag]
        if not any(gap == tag or gap in tag or tag in gap
                   for tag in named for gap in gap_skills):
            continue
        answer = question.get("answer") or ""
        claim = _has_claim(answer)
        if claim and not _is_honest(answer):
            invented.append(index)
    checks.append(_row(
        "no unsupported experience is invented", not invented,
        "no answer on a Gap skill claims hands-on experience" if not invented
        else f"{len(invented)} answer(s) on Gap skills claim experience the resume "
             f"does not support", invented))

    # --- coverage
    #
    # Matched loosely on purpose. The model is asked to tag questions with the
    # matrix's own skill names and mostly does, but "CI/CD" comes back as
    # "CI/CD pipelines" often enough that an exact match would fail this check
    # daily on wording. A daily false alarm is a check nobody reads.
    major = [row for row in matrix if row["importance"] in ("Critical", "High")]
    covered = set()
    for question in questions:
        for skill in [question.get("skill")] + (question.get("secondary_skills") or []):
            if skill:
                covered.add(_slug(skill))

    missed = []
    for row in major:
        key = _slug(row["skill"])
        if not any(key == tag or key in tag or tag in key for tag in covered if tag):
            missed.append(row["skill"])
    checks.append(_row(
        "major JD skills have question coverage", not missed,
        f"all {len(major)} Critical/High skills covered" if not missed
        else f"no question tagged to: {', '.join(missed)}"))

    checks.append(_row(
        "skill gaps are identified", bool(gap_skills),
        f"{len(gap_skills)} gap skill(s) identified"
        if gap_skills else "no gaps found - check the matcher, that is unusual"))

    ok = all(check["ok"] for check in checks)
    return {"ok": ok, "checks": checks,
            "counts": counts, "total": len(questions),
            "failed": [c["check"] for c in checks if not c["ok"]]}


def repairable(result: dict) -> set[int]:
    """Question indices a targeted regeneration should replace.

    Count checks are excluded: a short batch is fixed by generating more, not
    by replacing something.
    """
    wanted = {
        "every question has an answer",
        "questions are relevant to the Top 10 JDs",
        "questions are relevant to the profile",
        "no duplicate or near-duplicate questions",
        "no unsupported experience is invented",
    }
    indices: set[int] = set()
    for check in result["checks"]:
        if not check["ok"] and check["check"] in wanted:
            indices.update(check["indices"])
    return indices


def summarise(result: dict) -> str:
    lines = ["", "  Validation:"]
    for check in result["checks"]:
        mark = "PASS" if check["ok"] else "FAIL"
        lines.append(f"    [{mark}] {check['check']} - {check['detail']}")
    lines.append("")
    return "\n".join(lines)
