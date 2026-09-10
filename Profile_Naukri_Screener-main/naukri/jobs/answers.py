"""Answer a recruiter's screening question - but only from facts.

The rule this module exists to enforce: an answer is only ever given when it is
a fact already on record. Two sources count as on record.

    1. Your Naukri profile      notice period, current CTC, total experience,
                                current location, per-skill years from the IT
                                skills table
    2. The `answers:` block     things a profile has no field for - expected
       in jobs.yaml             CTC, willingness to relocate - which you state
                                once, in your own words

Anything else returns None and the job goes to the review queue unanswered.
That is the whole point: "what is your expected CTC" answered wrong by a guess
gets you screened out silently, and you never learn what was said on your
behalf.

`resolve()` returns (answer, reason). A None answer still carries a reason, so
the report can say *why* a job was left for you rather than just that it was.
"""
from __future__ import annotations

import re

# Each rule is (name, question pattern, fact key). Order matters: the first
# pattern that matches the question text wins, so put the specific ones first.
# "expected ctc" must be tested before "ctc", or every salary question resolves
# to your current pay.
RULES: list[tuple[str, str, str]] = [
    ("expected_ctc", r"expect\w*\s+(ctc|salary|compensation|package)", "expected_ctc_lpa"),
    ("current_ctc", r"(current|present)\s+(ctc|salary|compensation|package)|current\s+fixed", "current_ctc_lpa"),
    ("notice_period", r"notice\s*period|when\s+can\s+you\s+join|how\s+soon.*join", "notice_period_months"),
    ("total_experience", r"total\s+(work\s+)?experience|years\s+of\s+experience(?!\s+in)|overall\s+experience", "total_experience_years"),
    ("current_location", r"current\s+(location|city)|where\s+are\s+you\s+(currently\s+)?(based|located)", "current_location"),
    ("relocate", r"(willing|open)\s+to\s+relocat|can\s+you\s+relocat", "willing_to_relocate"),
    ("notice_buyout", r"notice\s*(period\s*)?buy\s*out", "notice_buyout"),
]

# Questions about one named skill - "how many years in Playwright", "do you
# have experience with Selenium" - are answered from the per-skill record, NOT
# from total experience. Getting this wrong is the worst failure this module
# has: answering "6.25" to "years of experience in Playwright" overstates a
# 1.25-year skill by five years, to a recruiter, in writing.
SKILL_PHRASE = re.compile(
    r"\b(?:in|with|using|on)\s+([A-Za-z][A-Za-z0-9+#./]*(?:\s+[A-Za-z0-9+#./]+){0,3})",
    re.IGNORECASE,
)

# Marks the question as asking for a duration rather than a yes/no.
DURATION_QUESTION = re.compile(r"\byears?\b|\bmonths?\b|how long|how much experience", re.IGNORECASE)

# Words that follow "in"/"with" without naming a skill, so a question like
# "are you comfortable with a 6-day work week" is not read as a skill question.
SKILL_STOPWORDS = {
    "a", "an", "the", "this", "that", "your", "our", "their", "years", "year",
    "months", "month", "total", "it", "india", "hand", "case", "general",
    "which", "what", "work", "working", "current", "us", "we", "me", "you",
    "any", "some", "detail", "details", "short", "brief", "mind", "person",
}

AFFIRMATIVE = ("yes", "y", "true")
NEGATIVE = ("no", "n", "false")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _parse_lpa(text: str | None) -> float | None:
    """'₹ 15,75,000' or '15.75 LPA' or '1575000' -> 15.75 (lakhs per annum)."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(text))
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    # Anything above 1000 is rupees, not lakhs.
    return round(value / 100000, 2) if value > 1000 else value


def _parse_months(text: str | None) -> int | None:
    """'2 Months notice period' -> 2. 'Immediate' -> 0."""
    if not text:
        return None
    low = _norm(text)
    if "immediate" in low:
        return 0
    months = re.search(r"(\d+)\s*month", low)
    if months:
        return int(months.group(1))
    days = re.search(r"(\d+)\s*day", low)
    if days:
        return max(0, round(int(days.group(1)) / 30))
    return None


def _parse_years(text: str | None) -> float | None:
    if not text:
        return None
    years = re.search(r"(\d+)\s*year", text, re.IGNORECASE)
    months = re.search(r"(\d+)\s*month", text, re.IGNORECASE)
    if not years and not months:
        return None
    total = float(years.group(1)) if years else 0.0
    total += (float(months.group(1)) / 12) if months else 0.0
    return round(total, 2)


def build_facts(profile: dict, config: dict) -> dict:
    """Everything answerable, gathered from the profile and jobs.yaml."""
    stated = {str(k).lower(): v for k, v in (config.get("answers") or {}).items()}

    skill_years: dict[str, float] = {}
    for row in profile.get("it_skills") or []:
        # "Playwright - 2025 1 Year 3 Months"
        name = re.split(r"\s+[-\d]", row, maxsplit=1)[0].strip().lower()
        years = _parse_years(row)
        if name and years is not None:
            skill_years[name] = years

    # Years you have stated per skill in jobs.yaml, layered over whatever the
    # profile's IT-skills table records. The table usually lists only a couple
    # of skills, so without this every "how many years of X" is a refusal.
    for name, years in (config.get("skill_years") or {}).items():
        try:
            skill_years[str(name).strip().lower()] = float(years)
        except (TypeError, ValueError):
            continue

    facts = {
        # Your own question -> answer rules from jobs.yaml, checked before
        # anything else. These are still facts you stated; the agent is not
        # deciding them, it is repeating what you wrote.
        # A rule needs either an answer to give or `skip: true`, which is a
        # rule that deliberately declines. Without the second form the only
        # way to keep a broad catch-all from agreeing to something is to
        # answer "No" to it, and "No" to "are you ok with a 2 year bond" is
        # just as much an invented answer as "Yes" - it is a position you may
        # not hold, sent to a recruiter in your name.
        "_rules": [
            r for r in (config.get("answer_rules") or [])
            if isinstance(r, dict) and r.get("match")
            and (r.get("answer") is not None or r.get("skip"))
        ],
        "notice_period_months": _parse_months(profile.get("notice_period")),
        "current_ctc_lpa": _parse_lpa(profile.get("current_salary")),
        "total_experience_years": _parse_years(profile.get("experience")),
        "current_location": (profile.get("location") or "").split(",")[0].strip() or None,
        "skill_years": skill_years,
        "skills": [s.lower() for s in (config.get("profile_skills") or [])],
        # Not on any profile - only ever what you stated in jobs.yaml.
        "expected_ctc_lpa": _parse_lpa(stated.get("expected_ctc")) if stated.get("expected_ctc") else None,
        "willing_to_relocate": stated.get("willing_to_relocate"),
        "notice_buyout": stated.get("notice_buyout"),
    }
    for key, value in stated.items():
        facts.setdefault(f"stated_{key}", value)
    return facts


def _format(key: str, value) -> str:
    if value is None:
        return ""
    if key == "notice_period_months":
        return "Immediate" if value == 0 else f"{value:g}"
    if key in ("current_ctc_lpa", "expected_ctc_lpa"):
        return f"{value:g}"
    if key == "total_experience_years":
        return f"{value:g}"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


INFINITY = float("inf")

# Choice labels meaning "none at all".
_ZERO_LABELS = ("no experience", "none", "fresher", "not applicable", "n/a", "na", "immediate")


def _parse_band(option: str) -> tuple[float, float] | None:
    """Read a choice label as the numeric range it stands for.

        "No experience"   -> (0, 0)
        "<5 years"        -> (0, 5)
        "5-6 years"       -> (5, 6)
        ">9 years"        -> (9, inf)
        "15 days or less" -> (0, 15)
        "2 months"        -> (2, 2)
    """
    text = _norm(option)
    if not text:
        return None
    if any(label in text for label in _ZERO_LABELS) and not re.search(r"\d", text):
        return (0.0, 0.0)

    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None

    # A range: "5-6", "5 to 6". Checked first, or "5-6" reads as a bare 5.
    span = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", text)
    if span:
        low, high = float(span.group(1)), float(span.group(2))
        return (min(low, high), max(low, high))

    value = numbers[0]
    if re.search(r"<|less than|under|below|upto|up to|or less|and below|or below", text):
        return (0.0, value)
    if re.search(r">|more than|greater than|above|over|\+|or more|and above|or above", text):
        return (value, INFINITY)
    return (value, value)


def choose_option(answer: str, options: list[str]) -> str | None:
    """Map a resolved answer onto one of the offered choices.

    Naukri asks most questions as chips rather than free text, so "2" has to
    become whichever of "1 month", "2 months", "3 months" is on screen.
    """
    if not options:
        return None
    answer_l = _norm(answer)
    if not answer_l:
        return None

    for option in options:
        if _norm(option) == answer_l:
            return option

    # Yes/no
    if answer_l in AFFIRMATIVE or answer_l in NEGATIVE:
        want = AFFIRMATIVE if answer_l in AFFIRMATIVE else NEGATIVE
        for option in options:
            if _norm(option) in want:
                return option
        return None

    # Numeric. Options are often bands rather than single values - "No
    # experience", "<5 years", "5-6 years", ">9 years" - so match by which
    # band contains the answer, preferring the tightest. Treating each option
    # as a single number picks "<5 years" for an answer of 5, when "5-6 years"
    # is sitting right there.
    number = re.search(r"\d+(?:\.\d+)?", answer_l)
    if number:
        target = float(number.group())
        best, best_width = None, None
        for option in options:
            band = _parse_band(option)
            if band is None:
                continue
            low, high = band
            if not (low <= target <= high):
                continue
            width = high - low
            if best_width is None or width < best_width:
                best, best_width = option, width
        if best is not None:
            return best

        # No band contains it. Fall back to nearest single value, but only if
        # it is genuinely close - "2 months" must not resolve to "6 months".
        best, best_gap = None, None
        for option in options:
            found = re.search(r"\d+(?:\.\d+)?", option)
            if not found:
                continue
            gap = abs(float(found.group()) - target)
            if best_gap is None or gap < best_gap:
                best, best_gap = option, gap
        if best is not None and best_gap is not None and best_gap <= 1.0:
            return best
        if target == 0:
            for option in options:
                if "immediate" in _norm(option):
                    return option
        return None

    for option in options:
        if answer_l in _norm(option) or _norm(option) in answer_l:
            return option
    return None


def resolve(question: str, options: list[str], facts: dict) -> tuple[str | None, str]:
    """Answer one question from facts, or explain why it cannot be answered."""
    text = _norm(question)
    if not text:
        return None, "empty question"

    # Rules you wrote in jobs.yaml win over everything - they are the most
    # specific statement of what you want said.
    for rule in facts.get("_rules") or []:
        try:
            if not re.search(str(rule["match"]), text, re.IGNORECASE):
                continue
        except re.error:
            continue
        if rule.get("skip"):
            return None, (f"your rule {rule['match']!r} keeps this one for you "
                          "- the job is queued unanswered")
        return _format("_rule", rule["answer"]), f"your rule {rule['match']!r}"

    # Skill-specific questions are handled before the generic rules, because
    # "how many years of experience do you have in Playwright" also matches the
    # total-experience pattern - and answering it with your total is a lie.
    skill_answer = _resolve_skill(text, facts)
    if skill_answer is not None:
        return skill_answer

    for name, pattern, key in RULES:
        if not re.search(pattern, text):
            continue
        value = facts.get(key)
        if value is None or value == "":
            hint = (
                f"no fact for '{name}'"
                if key not in ("expected_ctc_lpa", "willing_to_relocate", "notice_buyout")
                else f"'{name}' is not on your profile - set answers.{name} in jobs.yaml"
            )
            return None, hint
        return _format(key, value), f"from {name}"

    return None, "no rule matches this question"


def _skill_candidates(text: str) -> list[str]:
    """Skill names named after 'in'/'with'/'using', best candidate first."""
    out = []
    for match in SKILL_PHRASE.finditer(text):
        candidate = _norm(match.group(1))
        head = candidate.split(" ")[0] if candidate else ""
        if len(candidate) < 3 or head in SKILL_STOPWORDS:
            continue
        out.append(candidate)
    return out


def _lookup(candidate: str, known: dict | list):
    """Match a candidate against a known skill, longest overlap wins."""
    names = known.keys() if isinstance(known, dict) else known
    best = None
    for name in names:
        if not name:
            continue
        if name in candidate or candidate in name:
            if best is None or len(name) > len(best):
                best = name
    return best


def _resolve_skill(text: str, facts: dict) -> tuple[str | None, str] | None:
    """Answer a question about one named skill, or None if it is not one."""
    candidates = _skill_candidates(text)
    if not candidates:
        return None

    wants_duration = bool(DURATION_QUESTION.search(text))
    skill_years = facts.get("skill_years") or {}
    skills = facts.get("skills") or []

    # Prefer a candidate we actually know something about.
    for candidate in candidates:
        if wants_duration:
            known = _lookup(candidate, skill_years)
            if known:
                return f"{skill_years[known]:g}", f"IT-skills table: {known}"
        else:
            known = _lookup(candidate, skill_years) or _lookup(candidate, skills)
            if known:
                return "Yes", f"skills list: {known}"

    candidate = candidates[0]
    if wants_duration:
        # It asked how long, about something we have no duration for. Refuse
        # rather than falling through to the generic rules, which would answer
        # a skill-specific question with a whole-career number.
        if _lookup(candidate, skills):
            return None, f"'{candidate}' is in your skills but has no recorded years"
        return None, f"no experience recorded for '{candidate}'"

    # Not a duration question, and nothing matched. It may not be a skill
    # question at all - "what is your current CTC in lakhs" lands here - so let
    # the generic rules have it.
    return None
