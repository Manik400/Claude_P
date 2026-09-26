"""Regression tests for the screening-question resolver.

Run: python -m pytest tests/ -q      (or: python tests/test_answers.py)

The cases that matter most are the refusals. This module's only real failure
mode is confidently answering a question it should have left alone - a wrong
answer about notice period or skill depth goes to a recruiter in writing, and
you never find out what was said.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.jobs import answers  # noqa: E402

PROFILE = {
    "experience": "2 years",
    "notice_period": "1 Months notice period",
    "current_salary": "₹ 900000",
    "location": "India",
    "it_skills": [
        "Playwright - 2025 1 Year 3 Months",
        "Python 3.12 2025 2 Years 1 Month",
    ],
}
CONFIG = {
    "profile_skills": ["QA Automation", "Selenium", "Pytest", "Playwright", "Python", "Jenkins"],
    "answers": {"expected_ctc": "14 LPA", "willing_to_relocate": True},
}

FACTS = answers.build_facts(PROFILE, CONFIG)

ANSWERED = [
    ("What is your notice period?", ["Immediate", "15 Days", "1 Month", "2 Months", "3 Months"], "1 Month"),
    ("What is your current CTC?", [], "9"),
    ("What is your current CTC in lakhs?", [], "9"),
    ("What is your expected CTC?", [], "14"),
    ("How many years of total experience do you have?", [], "2"),
    ("What is your total experience in years?", [], "2"),
    ("What is your current location?", [], "India"),
    ("Are you willing to relocate to Hyderabad?", ["Yes", "No"], "Yes"),
    # Per-skill duration comes from the IT-skills table, never from the total.
    ("How many years of experience do you have in Playwright?", [], "1.25"),
    ("How many years of experience in Python?", [], "2.08"),
    ("Do you have experience in Selenium?", ["Yes", "No"], "Yes"),
]

REFUSED = [
    # Overstating a 1.25-year skill as 6.25 years is the worst thing this
    # module could do, so an unknown skill must never borrow the total.
    "How many years of experience do you have in Kubernetes?",
    # In the skills list, but with no duration recorded - still a refusal.
    "How many years of experience do you have in Selenium?",
    "Do you have experience in Salesforce CPQ?",
    "Are you comfortable with a 6-day work week?",
    "Why do you want to join our company?",
    "What is your father's occupation?",
    "What is your expected joining bonus?",
]


def _resolve(question, options):
    answer, reason = answers.resolve(question, options, FACTS)
    if answer and options:
        return answers.choose_option(answer, options), reason
    return answer, reason


def test_answers_from_facts():
    for question, options, expected in ANSWERED:
        got, reason = _resolve(question, options)
        assert got == expected, f"{question!r} -> {got!r}, expected {expected!r} ({reason})"


def test_refuses_what_it_cannot_know():
    for question in REFUSED:
        got, reason = _resolve(question, [])
        assert got is None, f"{question!r} should be refused but answered {got!r} ({reason})"


def test_option_mapping_never_guesses_wildly():
    notice = ["Immediate", "15 Days", "1 Month", "2 Months", "3 Months"]
    assert answers.choose_option("2", notice) == "2 Months"
    assert answers.choose_option("Immediate", ["Immediate", "30 Days"]) == "Immediate"
    assert answers.choose_option("Yes", ["Yes", "No"]) == "Yes"
    # No close option: refuse rather than snap to the nearest chip.
    assert answers.choose_option("2", ["6 Months", "12 Months"]) is None
    assert answers.choose_option("Pune", ["Chennai", "Kolkata"]) is None


def test_banded_options_pick_the_tightest_containing_band():
    bands = ["No experience", "<5 years", "5-6 years", "6-7 years", "7-8 years", ">9 years"]
    # 5 sits in both "<5 years" and "5-6 years"; the tighter one is right.
    assert answers.choose_option("5", bands) == "5-6 years"
    assert answers.choose_option("1.25", bands) == "<5 years"
    assert answers.choose_option("6.25", bands) == "6-7 years"
    assert answers.choose_option("12", bands) == ">9 years"
    assert answers.choose_option("0", bands) == "No experience"
    # Bands must not swallow a mismatched unit: 2 months is not 2 years.
    notice = ["Immediate", "15 days or less", "1 month", "2 months", "3 months"]
    assert answers.choose_option("2", notice) == "2 months"


def test_your_own_rules_win():
    facts = answers.build_facts(PROFILE, dict(CONFIG, answer_rules=[
        {"match": "5 days office|work from office", "answer": "Yes"},
        {"match": "pay cut", "answer": "No"},
    ]))
    assert answers.resolve("Are you ok to work 5 days office", ["Yes", "No"], facts)[0] == "Yes"
    # A trap rule placed before the catch-all must still win.
    assert answers.resolve("Are you willing to take a pay cut?", ["Yes", "No"], facts)[0] == "No"


def test_stated_skill_years_layer_over_the_profile_table():
    facts = answers.build_facts(PROFILE, dict(CONFIG, skill_years={"selenium": 5}))
    answer, why = answers.resolve("How many years of experience in Selenium?", [], facts)
    assert answer == "5", (answer, why)
    # The profile's own table still wins for what it records.
    assert answers.resolve("How many years of experience in Playwright?", [], facts)[0] == "1.25"


def test_expected_ctc_requires_you_to_have_stated_it():
    bare = answers.build_facts(PROFILE, {"profile_skills": [], "answers": {}})
    answer, reason = answers.resolve("What is your expected CTC?", [], bare)
    assert answer is None
    assert "jobs.yaml" in reason, reason


# ------------------------------------------------- the real jobs.yaml rules
#
# The rules in jobs.yaml are the owner's own answers, given to recruiters in
# their name, and a rule that never matches fails silently - the job is just
# quietly queued instead. On 2026-08-29 the catch-all willingness rule was
# found to have been dead since it was written: it was double-quoted, and a
# double-quoted YAML scalar resolves "\b" to a backspace (0x08) before the
# regex engine sees it, so the pattern required a literal control character
# no recruiter has ever typed. These tests read the shipped file.

def _shipped_rules() -> list[dict]:
    import yaml
    path = Path(__file__).resolve().parent.parent / "jobs.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("answer_rules") or []


def test_no_rule_pattern_contains_a_yaml_mangled_escape():
    """A control character in a pattern means a backslash escape was eaten."""
    for rule in _shipped_rules():
        pattern = rule["match"]
        bad = [c for c in pattern if ord(c) < 32]
        assert not bad, (
            f"{pattern!r} contains {bad!r} - the rule is double-quoted in "
            "jobs.yaml and YAML resolved its backslash escape. Single-quote it."
        )


def test_every_rule_pattern_compiles():
    for rule in _shipped_rules():
        re.compile(rule["match"], re.IGNORECASE)


def test_the_catch_all_actually_catches_willingness_questions():
    """The questions this rule exists for, in the wording recruiters use."""
    facts = answers.build_facts(PROFILE, dict(CONFIG, answer_rules=_shipped_rules()))
    for question in (
        "Are you comfortable with 5 days work from office?",
        "Are you ok with the notice period mentioned?",
        "Would you be available for a face to face interview?",
    ):
        answer, why = answers.resolve(question, ["Yes", "No"], facts)
        assert answer == "Yes", (question, answer, why)


def test_commitments_are_handed_back_not_agreed_to():
    """`skip: true` queues the job instead of answering.

    These were all answered "Yes" the moment the catch-all started working,
    because "comfortable (with|in|to)" happily matches "comfortable with a
    2 year bond". A bond, a contract role or third-party payroll may well be
    fine for the right job - but that is a decision, not a fact on record, so
    it goes back to the owner rather than out to a recruiter.
    """
    facts = answers.build_facts(PROFILE, dict(CONFIG, answer_rules=_shipped_rules()))
    for question in (
        "Are you comfortable with a 2 year bond?",
        "Would you be ok with a lower designation?",
        "Are you ok with third party payroll?",
        "Are you ok with a 6 month contract role?",
    ):
        answer, why = answers.resolve(question, ["Yes", "No"], facts)
        assert answer is None, (question, answer)
        assert "keeps this one for you" in why, why


def test_a_skill_claim_is_never_agreed_to():
    """"Comfortable working on Java" is a claim about experience, not a
    willingness question - and Java is a Gap skill on the owner's own matrix."""
    facts = answers.build_facts(PROFILE, dict(CONFIG, answer_rules=_shipped_rules()))
    answer, _ = answers.resolve("Are you comfortable working on Java based frameworks?",
                                ["Yes", "No"], facts)
    assert answer is None, answer


def test_a_skip_rule_does_not_block_the_rules_below_it():
    """Order still decides: a trap above a skip must still win."""
    facts = answers.build_facts(PROFILE, dict(CONFIG, answer_rules=_shipped_rules()))
    # "unpaid" is a trap and sits above every skip rule.
    assert answers.resolve("Are you ok with unpaid overtime?", ["Yes", "No"], facts)[0] == "No"
    # A plain willingness question is untouched by the skips.
    assert answers.resolve("Are you comfortable with 5 days work from office?",
                           ["Yes", "No"], facts)[0] == "Yes"


def test_the_traps_still_win_over_the_catch_all():
    """Rules are tried in order; a "Yes" to any of these would be false."""
    facts = answers.build_facts(PROFILE, dict(CONFIG, answer_rules=_shipped_rules()))
    for question in (
        "Are you willing to take a pay cut for this role?",
        "Can you join immediately?",
    ):
        answer, why = answers.resolve(question, ["Yes", "No"], facts)
        assert answer == "No", (question, answer, why)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n  {'all tests passed' if not failures else str(failures) + ' failure(s)'}")
    sys.exit(1 if failures else 0)


# ------------------------------------------------------------ local model
#
# The local model may answer what no rule covers - but only when grounded in
# the facts sheet. These drive resolve() with a fake model so no download is
# needed, and check every guard in _resolve_local_ai.

def _with_fake_ai(monkeypatch, reply):
    from naukri import localai

    monkeypatch.setattr(localai, "available", lambda kind="any": True)
    monkeypatch.setattr(localai, "answer_from_facts", lambda q, o, sheet: reply)


def test_facts_sheet_lists_facts_only():
    sheet = answers.facts_sheet(FACTS)
    assert "notice_period_months: 2" in sheet
    assert "skill_years.playwright: 1.25" in sheet
    assert "_rules" not in sheet and "_bank" not in sheet


def test_without_model_fallthrough_is_unchanged(monkeypatch):
    from naukri import localai

    monkeypatch.setattr(localai, "available", lambda kind="any": False)
    assert answers.resolve("Why do you want to join our company?", [], FACTS) == (None, "no rule matches this question")


def test_model_answer_is_used_when_grounded(monkeypatch):
    _with_fake_ai(monkeypatch, {"answer": "2 Months", "confidence": 0.95, "basis": "notice_period_months: 2"})
    answer, why = answers.resolve("When could you start with us?", ["Immediately", "2 Months", "6 Months"], FACTS)
    assert answer == "2 Months" and why.startswith("local-ai:")


def test_model_answer_rejected_when_unsure_or_ungrounded(monkeypatch):
    _with_fake_ai(monkeypatch, {"answer": "2 Months", "confidence": 0.4, "basis": "notice_period_months: 2"})
    assert answers.resolve("When could you start?", ["2 Months"], FACTS)[0] is None
    _with_fake_ai(monkeypatch, {"answer": "2 Months", "confidence": 0.95, "basis": "it seems reasonable"})
    assert answers.resolve("When could you start?", ["2 Months"], FACTS)[0] is None
    _with_fake_ai(monkeypatch, {"answer": "UNKNOWN", "confidence": 0.99, "basis": "notice_period_months"})
    assert answers.resolve("When could you start?", ["2 Months"], FACTS)[0] is None


def test_model_may_not_invent_numbers(monkeypatch):
    _with_fake_ai(monkeypatch, {"answer": "3 years", "confidence": 0.99, "basis": "skill_years.playwright: 1.25"})
    assert answers.resolve("How long have you used Cypress?", [], FACTS)[0] is None


def test_model_answer_must_map_to_an_option(monkeypatch):
    _with_fake_ai(monkeypatch, {"answer": "Pune", "confidence": 0.99, "basis": "current_location: Pune"})
    assert answers.resolve("Which office do you prefer?", ["Mumbai", "Delhi"], FACTS)[0] is None
    answer, _ = answers.resolve("Which office do you prefer?", ["Mumbai", "Pune"], FACTS)
    assert answer == "Pune"


def test_model_can_be_switched_off_in_config(monkeypatch):
    _with_fake_ai(monkeypatch, {"answer": "2 Months", "confidence": 0.99, "basis": "notice_period_months: 2"})
    facts = answers.build_facts(PROFILE, dict(CONFIG, local_ai_answers=False))
    assert answers.resolve("When could you start?", ["2 Months"], facts) == (None, "no rule matches this question")


def test_rules_and_refusals_still_win_over_the_model(monkeypatch):
    _with_fake_ai(monkeypatch, {"answer": "6.25", "confidence": 0.99, "basis": "total_experience_years: 6.25"})
    # An unknown skill's years are an explicit refusal, never handed to the model.
    answer, why = answers.resolve("How many years of experience do you have in Kubernetes?", [], FACTS)
    assert answer is None and "local-ai" not in why


# ------------------------------------------------ other wordings, place names, answer types

def test_a_saved_answer_covers_other_wordings_of_the_same_field(monkeypatch):
    from naukri import localai
    from naukri.jobs import questions

    monkeypatch.setattr(localai, "available", lambda kind="any": False)
    facts = dict(FACTS)
    facts["_bank"] = {questions.key(q): {"question": q, "answer": a} for q, a in [
        ("DOB (Date of Birth)", "23 / 09 / 2003"), ("LinkedIn Profile", "https://www.linkedin.com/in/me"),
        ("How many years with NestJS?", "1")]}
    for asked in ("Date of birth", "Date of Birth (DD/MM/YYYY)*", "D.O.B"):
        answer, why = answers.resolve(asked, [], facts)
        assert answer == "23 / 09 / 2003" and "saved answer" in why, (asked, answer, why)
    assert answers.resolve("Please provide your LinkedIn profile URL", [], facts)[0] == "https://www.linkedin.com/in/me"
    # different skills never share an answer
    assert answers.resolve("How many years with Django?", [], facts)[0] is None


def test_place_names_are_split_and_cleaned():
    facts = answers.build_facts(PROFILE, dict(CONFIG, fact_overrides={"current_location": "gurgaon ,haryana , india"}))
    assert answers.resolve("What is your current location?", [], facts)[0] == "Gurgaon"
    assert answers.resolve("State", [], facts)[0] == "Haryana"


def test_availability_to_join_is_the_notice_period_in_words():
    assert answers.resolve("When are you available to join?", [], FACTS)[0] == "2 months"
    assert answers.resolve("Notice period (in days)", [], FACTS)[0] == "60"


def test_yes_leads_an_option_sentence():
    assert answers.choose_option("Yes", ["Yes, I have joined", "No"]) == "Yes, I have joined"
    assert answers.choose_option("No", ["I agree", "I do not agree"]) == "I do not agree"


def test_model_yes_to_a_non_yes_no_question_is_refused(monkeypatch):
    _with_fake_ai(monkeypatch, {"answer": "yes", "confidence": 0.99, "basis": "stated_willing_to_relocate: yes"})
    assert answers.resolve("Which state do you live in", [], FACTS)[0] is None


def test_written_answers_need_the_model_and_stay_off_money_and_identity(monkeypatch):
    from naukri import localai

    calls = []
    monkeypatch.setattr(localai, "available", lambda kind="any": True)
    monkeypatch.setattr(localai, "answer_from_facts", lambda q, o, sheet: None)
    monkeypatch.setattr(localai, "write_answer", lambda q, ctx, ex, max_words=120: calls.append(q) or
                        {"answer": "I built the payments service in Python and Kafka end to end.", "confidence": 0.9})
    monkeypatch.setattr(answers, "_resume_text", lambda facts: "Python Kafka payments service " * 20)
    answer, why = answers.resolve("Something you shipped end to end that you're proud of?", [], FACTS)
    assert answer.startswith("I built") and why.startswith("ai-written")
    assert answers.resolve("What is your expected joining bonus?", [], FACTS)[0] is None
    assert answers.resolve("Tell us your father's occupation", [], FACTS)[0] is None
    assert calls == ["Something you shipped end to end that you're proud of?"]
    # a number the resume does not hold is never written
    monkeypatch.setattr(localai, "write_answer", lambda q, ctx, ex, max_words=120:
                        {"answer": "I cut latency by 73 percent for our payments service.", "confidence": 0.9})
    assert answers.resolve("Describe a challenge you solved", [], FACTS)[0] is None
