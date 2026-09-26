"""Answer a recruiter's screening question - but only from facts.

The rule this module exists to enforce: an answer is only ever given when it is
a fact already on record. Two sources count as on record.

    1. Your Naukri profile      notice period, current CTC, total experience,
                                current location, per-skill years from the IT
                                skills table
    2. The `answers:` block     things a profile has no field for - expected
       in jobs.yaml             CTC, willingness to relocate - which you state
                                once, in your own words
    3. The answer bank          questions you answered after a run left them
       data/jobs/answer_bank.yaml   for you (see questions.py) - also under other
                                    wordings ("DOB" answers "Date of birth")

With the local model (naukri/localai.py) two more, both checked before use:

    4. short factual questions answered from the facts sheet, your resume and
       your closest saved answers, when every number is on record
    5. open questions ("something you shipped that you're proud of") written
       from your resume and the job, marked "ai-written" in the applications log

Anything else returns None and the job goes to the review queue unanswered.
That is the whole point: "what is your expected CTC" answered wrong by a guess
gets you screened out silently, and you never learn what was said on your
behalf.

`resolve()` returns (answer, reason). A None answer still carries a reason, so
the report can say *why* a job was left for you rather than just that it was.
"""
from __future__ import annotations

import os
import re

# Each rule is (name, question pattern, fact key). Order matters: the first
# pattern that matches the question text wins, so put the specific ones first.
# "expected ctc" must be tested before "ctc", or every salary question resolves
# to your current pay.
RULES: list[tuple[str, str, str]] = [
    ("expected_ctc", r"expect\w*\s+(ctc|salary|compensation|package)", "expected_ctc_lpa"),
    ("current_ctc", r"(current|present)\s+(ctc|salary|compensation|package)|current\s+fixed", "current_ctc_lpa"),
    ("notice_period", r"notice\s*period|when\s+can\s+you\s+join|how\s+soon.*join|availab\w*\s+to\s+join|"
                      r"earliest\s+(joining|start)\s+date", "notice_period_months"),
    ("total_experience", r"total\s+(work\s+)?experience|years\s+of\s+experience(?!\s+in)|overall\s+experience", "total_experience_years"),
    ("current_location", r"current\s+(location|city)|where\s+are\s+you\s+(currently\s+)?(based|located)|^\W*city\W*$|city or location|^\W*location(\s*\(city\))?\W*$", "current_location"),
    ("current_state", r"^\W*(current\s+|home\s+)?(state|state\s*/\s*(province|region|ut)|province)\W*$|which\s+state\s+(are|do)\s+you|"
                      r"state\s+of\s+residence", "current_state"),
    ("relocate", r"(willing|open)\s+to\s+relocat|can\s+you\s+relocat", "willing_to_relocate"),
    # From the profile's education, employment and personal-details sections.
    ("highest_qualification", r"highest\s+(qualification|education|degree)|^\W*(qualification|education|degree)\W*$",
     "highest_qualification"),
    ("graduation_year", r"(graduation|passing|passed\s*out)\s*year|year\s+of\s+(graduation|passing)|when did you graduate",
     "graduation_year"),
    ("college", r"^\W*(college|university|institute)(\s*name)?\W*$|which (college|university)", "college"),
    ("current_title", r"^\W*(current\s+)?(job\s+)?(title|designation)\W*$|current\s+(job\s+)?(title|designation|role)",
     "current_title"),
    ("current_company", r"current\s+(company|employer|organi[sz]ation)|^\W*(current\s+)?(company|employer)(\s+name)?\W*$",
     "current_company"),
    ("date_of_birth", r"\bd\.?\s?o\.?\s?b\b|date\s*of\s*birth|birth\s*date", "date_of_birth"),
    ("gender", r"^\W*(your\s+)?gender\W*$|what is your gender", "gender"),
    ("marital_status", r"marital", "marital_status"),
    ("nationality", r"nationality|citizenship", "nationality"),
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
YES_LEAD = re.compile(r"(yes|yeah|sure|ok|okay|i (agree|accept|confirm|understand|have|will|am|do|can))\b")
NO_LEAD = re.compile(r"(no|nope|not)\b|i (do not|don'?t|have not|haven'?t|will not|won'?t|am not|cannot|can'?t)\b")


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


def _from_profile(profile: dict) -> dict:
    """What the profile's education, employment and personal-details text says, as facts."""
    personal = str(profile.get("personal_details") or "")
    # "B.Tech / B.E. Information Technology University School Of ... , Delhi 2021- 2025 Full Time"
    degree = next((str(e) for e in profile.get("education") or []
                   if not re.match(r"class\s+(x|xii|10|12)\b", str(e), re.I)), "")
    school = re.search(r"\b(University|College|Institute|School|IIT|NIT|IIIT)\b", degree)
    title_at = re.match(r"(.+?)\s+at\s+(.+)", str(profile.get("current_designation") or ""))
    born = re.search(r"date of birth\s+(\d{1,2}\s+\w{3,9}\s+\d{4})", personal, re.I)
    gender = re.search(r"\b(male|female)\b", personal, re.I)
    return {
        "highest_qualification": (degree[:school.start()] if school else re.split(r"\s+\d{4}", degree)[0]).strip(" ,/") or None,
        "graduation_year": (re.findall(r"\b(?:19|20)\d\d\b", degree) or [None])[-1],
        "college": re.split(r"\s+\d{4}", degree[school.start():])[0].replace(" ,", ",").strip(" ,") if school else None,
        "current_title": title_at.group(1).strip() if title_at else None,
        "current_company": title_at.group(2).strip() if title_at else None,
        "date_of_birth": born.group(1) if born else None,
        "gender": gender.group(1).title() if gender else None,
        "marital_status": "Single" if re.search(r"single|unmarried", personal, re.I)
                          else ("Married" if re.search(r"\bmarried\b", personal, re.I) else None),
    }


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
        "nationality": stated.get("nationality"),
        **_from_profile(profile),
    }
    for key, value in stated.items():
        facts.setdefault(f"stated_{key}", value)
    # Overrides typed into the dashboard for what the profile says.
    for key, value in (config.get("fact_overrides") or {}).items():
        if value not in (None, ""):
            facts[key] = value
    # "gurgaon ,haryana , india" -> city Gurgaon, state Haryana, country India
    place = [p.strip().title() for p in str((config.get("fact_overrides") or {}).get("current_location")
                                             or profile.get("location") or "").split(",") if p.strip()]
    if place:
        facts["current_location"] = place[0]
        if len(place) >= 3:
            facts["current_state"] = place[1]
        if len(place) >= 2:
            facts["current_country"] = place[-1]
    # The local model (naukri/localai.py) may answer what no rule covers -
    # from this sheet of facts only. jobs.yaml `local_ai_answers: false`
    # keeps every unmatched question for you instead.
    facts["_local_ai"] = bool(config.get("local_ai_answers", True))
    # ...and write answers to open questions from your resume (`ai_written_answers: false` stops it)
    facts["_ai_write"] = bool(config.get("ai_written_answers", True))
    facts["_applicant"] = dict(config.get("applicant") or {})
    facts["_facts_sheet"] = facts_sheet(facts)
    return facts


def facts_sheet(facts: dict) -> str:
    """The facts as `key: value` lines - what the local model is allowed to know.

    Everything you stated or the profile records, nothing else: no rules, no
    answer bank (those are matched exactly, not paraphrased by a model).
    """
    lines = []
    for key, value in facts.items():
        if key.startswith("_") or value in (None, "", [], {}):
            continue
        if key == "skill_years":
            for name, years in sorted(value.items()):
                lines.append(f"skill_years.{name}: {years:g}")
        elif key == "skills":
            lines.append("skills: " + ", ".join(str(v) for v in value))
        elif isinstance(value, bool):
            lines.append(f"{key}: {'yes' if value else 'no'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value:g}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


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

    # Yes/no - also "Yes, I have joined" / "I agree" / "No, I haven't"
    if answer_l in AFFIRMATIVE or answer_l in NEGATIVE:
        want = AFFIRMATIVE if answer_l in AFFIRMATIVE else NEGATIVE
        for option in options:
            if _norm(option) in want:
                return option
        lead = YES_LEAD if want is AFFIRMATIVE else NO_LEAD
        hits = [o for o in options if lead.match(_norm(o))]
        return hits[0] if len(hits) == 1 else None

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


def resolve(question: str, options: list[str], facts: dict, *, job: dict | None = None,
            long_text: bool = False) -> tuple[str | None, str]:
    """Answer one question from facts, or explain why it cannot be answered.

    `job` ({title, company, description}) and `long_text` (the field is a text
    area) only matter to the written-answer step for open questions.
    """
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

    # Then the answers you gave to earlier runs' questions. Exact question
    # match only - a saved answer must never be stretched to a different
    # question.
    from . import questions as questions_mod
    saved = questions_mod.lookup(question, facts.get("_bank"))
    if saved:
        if str(saved.get("answer", "")).strip().lower() == questions_mod.SKIP:
            return None, "you chose to skip this question (data/jobs/answer_bank.yaml)"
        return _format("_bank", saved.get("answer")), "your saved answer"
    # Skill-specific questions are handled before the generic rules, because
    # "how many years of experience do you have in Playwright" also matches the
    # total-experience pattern - and answering it with your total is a lie.
    skill_answer = _resolve_skill(text, facts)
    if skill_answer is not None:
        return skill_answer

    hint, found = None, []
    for name, pattern, key in RULES:
        if not re.search(pattern, text):
            continue
        value = facts.get(key)
        if value is None or value == "":
            if not found:
                hint = (
                    f"no fact for '{name}'"
                    if key not in ("expected_ctc_lpa", "willing_to_relocate", "notice_buyout")
                    else f"'{name}' is not on your profile - set answers.{name} in jobs.yaml"
                )
            break
        found.append((name, key, value))
        # "Years of experience and graduation year": a free-text box that asks two things
        if options or not re.search(r"\band\b|&|/", text):
            break
    if len(found) > 1:
        return ", ".join(_spoken(text, key, value) for _n, key, value in found), \
            "from " + " + ".join(name for name, _k, _v in found)
    if found:
        name, key, value = found[0]
        if key == "notice_period_months" and not options:
            return _notice_text(text, value), f"from {name}"
        return _format(key, value), f"from {name}"

    # The same question in other words ("DOB" was answered, "Date of birth" is asked).
    similar = questions_mod.find_similar(
        question, facts.get("_bank"), options,
        protect=set(facts.get("skills") or []) | set((facts.get("skill_years") or {}).keys()),
        use_model=bool(facts.get("_local_ai")) and not _open_question(question, options, long_text))
    if similar:
        entry, how = similar
        answer = str(entry.get("answer", "")).strip()
        if answer.lower() == questions_mod.SKIP:
            return None, f"you chose to skip this question ({how}: {entry['question'][:60]!r})"
        if not options or choose_option(answer, options) is not None:
            return _format("_bank", answer), f"your saved answer ({how}: {entry['question'][:60]!r})"
    if hint:
        return None, hint

    # Nothing you wrote covers it: the local model may answer from the facts
    # sheet, under the checks in _resolve_local_ai. Otherwise the question is
    # kept for you, as before.
    # An open question ("something you shipped ...") is prose, not a fact: straight to the
    # writer - the facts pass costs a minute of CPU and always says UNKNOWN to these.
    if not _open_question(question, options, long_text):
        ai = _resolve_local_ai(question, options, facts)
        if ai is not None:
            return ai
    written = _resolve_written(question, options, facts, job, long_text)
    if written is not None:
        return written
    return None, "no rule matches this question"


# How sure the model must say it is before an answer is used. The model's own
# confidence is a weak signal on its own; the basis and number checks below
# are what actually keep invented answers out.
AI_MIN_CONFIDENCE = 0.8
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _spoken(question: str, key: str, value) -> str:
    """One fact inside a longer free-text answer, with its unit."""
    if key == "notice_period_months":
        return _notice_text(question, value)
    if key == "total_experience_years":
        return f"{float(value):g} years"
    if key in ("current_ctc_lpa", "expected_ctc_lpa"):
        return f"{float(value):g} LPA"
    return _format(key, value)


def _notice_text(question: str, months) -> str:
    """A notice period typed into a text box: in the unit the question asks for."""
    try:
        months = float(months)
    except (TypeError, ValueError):
        return str(months)
    if re.search(r"\bdays?\b", question):
        return f"{months * 30:g}"
    if re.search(r"\bmonths?\b", question):
        return f"{months:g}"
    if months == 0:
        return "Immediate"
    return f"{months:g} month" + ("" if months == 1 else "s")


YES_NO_QUESTION = re.compile(r"^\W*(are|do|does|did|have|has|had|can|could|will|would|is|was|were|should|shall|may|"
                             r"any|ok|okay)\b|\byes\s*/\s*no\b|\(y/n\)|willing|comfortable|agree|mandatory|"
                             r"compulsory|confirm", re.I)
NUMBER_QUESTION = re.compile(r"how many|how much|\byears?\b|number of|\bctc\b|salary|\blpa\b|notice|percentage|"
                             r"\bcgpa\b|\bgpa\b|\bage\b", re.I)


def _fits(question: str, answer: str, options: list[str]) -> bool:
    """Is this the kind of answer the question wants? "yes" to "State" is not."""
    if options:
        return True
    low = _norm(answer)
    if (low in AFFIRMATIVE or low in NEGATIVE) and not YES_NO_QUESTION.search(question):
        return False
    if NUMBER_QUESTION.search(question) and not re.search(r"\d", answer) and "immediate" not in low:
        return False
    if re.search(r"\bdate\b|\bd\.?o\.?b\b|birth", question, re.I) and not re.search(r"\d", answer):
        return False
    return True


def _resume_text(facts: dict) -> str:
    """Your resume's text, read once per run (for the model only)."""
    if "_resume_text" not in facts:
        try:
            from . import career_apply
            facts["_resume_text"] = career_apply._resume_text(
                career_apply._resume_path({"applicant": facts.get("_applicant") or {}}))[:6000]
        except Exception:  # noqa: BLE001 - no resume, no written answers
            facts["_resume_text"] = ""
    return facts["_resume_text"]


def _examples(question: str, facts: dict, n: int = 6) -> list[tuple[str, str]]:
    """Your closest saved answers, shown to the model as how you answer."""
    from . import questions as questions_mod
    return [(e["question"], str(e["answer"])) for e in questions_mod.similar_entries(question, facts.get("_bank"), n)]


def _resolve_local_ai(question: str, options: list[str], facts: dict) -> tuple[str, str] | None:
    """An answer from the local model, or None. Accepted only when it is
    grounded: the basis names a fact, every number in it is a fact's value,
    and (with options) it maps onto one of the chips."""
    if not facts.get("_local_ai"):
        return None
    try:
        from naukri import localai
    except Exception:  # noqa: BLE001
        return None
    if not localai.available("llm"):
        return None
    sheet = facts.get("_facts_sheet") or facts_sheet(facts)
    if not sheet.strip():
        return None
    # Your closest saved answers and your resume go on the sheet too: that is how
    # "Graduation year" gets answered from the resume and every answer you give
    # makes the next unfamiliar question easier.
    extra = [f"answered: {q} => {a}" for q, a in _examples(question, facts)]
    resume = re.sub(r"\s+", " ", _resume_text(facts))[:2500]
    if resume:
        extra.append("resume: " + resume)
    sheet = "\n".join([sheet] + extra)
    try:
        threshold = float(os.environ.get("LOCAL_AI_ANSWER_MIN_CONFIDENCE") or AI_MIN_CONFIDENCE)
    except ValueError:
        threshold = AI_MIN_CONFIDENCE
    out = localai.answer_from_facts(question, options or [], sheet)
    if not out:
        return None
    answer = str(out.get("answer") or "").strip()
    basis = str(out.get("basis") or "").strip()
    if not answer or answer.upper() == "UNKNOWN" or float(out.get("confidence") or 0) < threshold:
        return None
    if not _fits(question, answer, options):
        return None
    # The basis must point at a line of the sheet: a key, or a value of substance.
    keys = [line.split(":", 1)[0].strip().lower() for line in sheet.splitlines() if ":" in line]
    values = [line.split(":", 1)[1].strip().lower() for line in sheet.splitlines() if ":" in line]
    basis_l = basis.lower()
    grounded = any(k and k in basis_l for k in keys) or any(len(v) >= 2 and v in basis_l for v in values)
    if not grounded:
        return None
    # Every number in the answer must be a number the sheet holds - a notice
    # period, a CTC or a year count is never the model's to make up.
    # (the resume and your earlier answers may add calendar years - a graduation year - never durations)
    fact_numbers = {float(n) for n in _NUMBER.findall(facts.get("_facts_sheet") or facts_sheet(facts))}
    fact_numbers |= {float(n) for n in re.findall(r"\b(?:19|20)\d\d\b", sheet)}
    for n in _NUMBER.findall(answer):
        if float(n) not in fact_numbers:
            return None
    if options:
        chip = choose_option(answer, options)
        if chip is None:
            return None
        answer = chip
    return answer, f"local-ai: {basis[:80]}"


# Open questions the model may write an answer to from your resume...
OPEN_QUESTION = re.compile(
    r"^\W*(why|describe|tell|explain|share|walk|give an example|what (is|was|are|were) (something|a time|one|the most|your "
    r"(biggest|greatest|favou?rite|proudest|approach|experience))|how (did|would|do) you|what (excites|interests|motivates)|"
    r"introduce)|something you|a time (when|you)|proud of|exceptional|cover letter|about yourself|summary|motivat|"
    r"why (do|are|would) you|what makes you|anything else|additional information|elaborate", re.I)
# ...and the ones it never may: money, family, identity, legal - facts, not prose.
NEVER_WRITE = re.compile(
    r"salary|\bctc\b|compensation|bonus|\blpa\b|stipend|father|mother|spouse|religion|caste|marital|\bage\b|"
    r"birth|gender|visa|sponsor|criminal|convict|disabilit|aadhaar|\bpan\b|passport|bank|password|reference|"
    r"notice|join(ing)? date|relocat|expected|current (location|city)|phone|e-?mail|address", re.I)
PLACEHOLDER_TEXT = re.compile(r"\[[^\]]*\]|<[^>]*>|\bXYZ\b|company name|your name|lorem ipsum|as an ai\b", re.I)
AI_WRITE_MIN_CONFIDENCE = 0.6
OPINION = re.compile(r"you (think|admire|like|love|find)|favou?rite|well[- ]built|well[- ]designed|exceptional|inspir", re.I)


def _open_question(question: str, options: list[str], long_text: bool) -> bool:
    """Free text asking for prose the model may write (see OPEN_QUESTION / NEVER_WRITE)."""
    return not options and not NEVER_WRITE.search(question) and bool(long_text or OPEN_QUESTION.search(question))


def _resolve_written(question: str, options: list[str], facts: dict, job: dict | None,
                     long_text: bool) -> tuple[str, str] | None:
    """An answer to an open question, written by the local model from your resume and the job.

    Only for free text, never for money / identity / legal questions, and every
    number in it must appear in your resume, your facts or the job posting.
    """
    if not facts.get("_local_ai") or not facts.get("_ai_write") or not _open_question(question, options, long_text):
        return None
    try:
        from naukri import localai
    except Exception:  # noqa: BLE001
        return None
    if not localai.available("llm"):
        return None
    resume = _resume_text(facts)
    if len(resume) < 200:
        return None
    job = job or {}
    posting = re.sub(r"\s+", " ", str(job.get("description") or ""))[:1500]
    context = "\n\n".join(filter(None, [
        "RESUME:\n" + resume[:3500],
        "FACTS:\n" + (facts.get("_facts_sheet") or facts_sheet(facts)),
        ("THE JOB: %s at %s\n%s" % (job.get("title") or "", job.get("company") or "", posting)) if job else "",
    ]))
    limit = re.search(r"(\d{2,4})\s*(words|word)", question, re.I)
    max_words = min(int(limit.group(1)), 250) if limit else (150 if long_text else 70)
    if not limit and re.search(r"one sentence|one line|in brief|briefly|short answer", question, re.I):
        max_words = 45
    examples = [(q, a) for q, a in _examples(question, facts, 8) if len(a) > 25][:4]
    asked = question
    if OPINION.search(question):
        # a small model otherwise describes your own project here
        asked = ("(Opinion question - name a well-known product or tool from the technologies in the context, "
                 "not the candidate's own project, and say why it is well made.) " + question)
    out = localai.write_answer(asked, context, examples, max_words=max_words)
    if not out:
        return None
    answer = re.sub(r"\s+", " ", str(out.get("answer") or "")).strip().strip('"')
    if not answer or answer.upper().startswith("UNKNOWN") or float(out.get("confidence") or 0) < AI_WRITE_MIN_CONFIDENCE:
        return None
    if len(answer) < 20 or PLACEHOLDER_TEXT.search(answer):
        return None
    words = answer.split()
    if len(words) > max_words:
        answer = " ".join(words[:max_words]).rstrip(",;") + "."
    known = {float(n) for n in _NUMBER.findall(context)}
    if any(float(n) not in known for n in _NUMBER.findall(answer)):
        return None
    return answer, "ai-written from your resume"


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
