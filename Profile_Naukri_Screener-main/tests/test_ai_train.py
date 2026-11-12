"""The personal model's examples: only clean ones, and never more than the context window holds."""
from naukri.jobs import ai_train


def entry(question, answer, options=None):
    return {"question": question, "answer": answer, "options": options or []}


def test_clean_examples_are_kept_in_bank_order():
    bank = [entry("Notice period?", "Immediate"), entry("Willing to relocate?", "Yes", ["Yes", "No"])]
    assert ai_train.select_examples(bank) == [
        ("Notice period?", "Immediate"),
        ("Willing to relocate?\nOPTIONS: Yes | No", "Yes"),
    ]


def test_answer_outside_the_questions_own_options_is_left_out():
    bank = [
        entry("Passport", "Yes", ["I have a British or Irish passport", "I will require sponsorship"]),
        entry("Highest degree", "B.Tech / B.E. Information Technology", ["High school", "Bachelor's degree"]),
        entry("Gender", "male", ["Male", "Female"]),  # case does not matter
    ]
    assert [a for _, a in ai_train.select_examples(bank)] == ["male"]


def test_placeholders_and_empty_answers_are_left_out():
    bank = [entry("Details", "free text"), entry("Other", "  "), entry("", "x"), entry("Current company", "I2V Systems")]
    assert ai_train.select_examples(bank) == [("Current company", "I2V Systems")]


def test_huge_dropdowns_never_reach_the_model():
    universities = [f"University {i}" for i in range(3302)]
    bank = [entry("University", "University 7", universities), entry("City", "Gurugram")]
    assert ai_train.select_examples(bank) == [("City", "Gurugram")]


def test_a_question_answered_again_keeps_only_the_latest_answer():
    bank = [entry("Expected CTC?", "1500000"), entry("City", "Gurugram"), entry("expected  ctc?", "1800000")]
    assert ai_train.select_examples(bank) == [("City", "Gurugram"), ("expected  ctc?", "1800000")]


def test_examples_stay_inside_the_budget_and_prefer_the_newest():
    bank = [entry(f"Question number {i} about something specific?", "Yes") for i in range(500)]
    picked = ai_train.select_examples(bank)
    assert sum(len(q) + len(a) for q, a in picked) <= ai_train.EXAMPLE_BUDGET_CHARS
    assert len(picked) <= ai_train.MAX_EXAMPLES
    assert picked[-1][0] == "Question number 499 about something specific?"


def test_built_prompt_fits_the_context_window(monkeypatch):
    """Even with a full, messy bank the Modelfile must be well under NUM_CTX tokens (~4 chars each)."""
    from naukri.jobs import answers, config as config_mod, questions
    bank = [entry(f"Q{i} " + "word " * 30, "Yes") for i in range(300)] + [entry("U", "u1", ["u%d" % i for i in range(5000)])]
    monkeypatch.setattr(questions, "_read_list", lambda path: bank)
    monkeypatch.setattr(config_mod, "load_profile", lambda: {})
    monkeypatch.setattr(config_mod, "load", lambda profile=None: {})
    monkeypatch.setattr(answers, "build_facts", lambda profile, cfg: {"_facts_sheet": "total_experience_years: 2.2\n" * 80})
    text, n = ai_train.modelfile("qwen3:8b")
    assert f"PARAMETER num_ctx {ai_train.NUM_CTX}" in text
    assert text.startswith("FROM qwen3:8b\nSYSTEM ")
    assert n > 0 and len(text) / 4 < ai_train.NUM_CTX * 0.6
