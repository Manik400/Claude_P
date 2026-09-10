"""Regression tests for the interview-preparation module.

Run: python -m pytest tests/ -q      (or: python tests/test_interview.py)

Nothing here calls a model. What is tested is everything that decides whether
the model's output is usable: the concept-key duplicate detector, the skill
matrix, and the validation gate.

The duplicate cases are the ones that matter. The module's promise is 100
questions testing 100 different things, and its natural failure mode is a
polite reword of a question that is already in the set - which a reader only
notices after studying both.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from naukri.interview import dedupe, generate, page, skills, validate  # noqa: E402


# ------------------------------------------------------------------- top ten

def test_top_ten_is_by_score_not_scan_order():
    """The scan writes remote-first under --worldwide, not score-first.

    On 2026-08-25 that put a 56.9 remote role at the head of the results file
    and pushed a 62.5 out of the ten entirely, so the prep studied a weaker
    match than the scan had actually found.
    """
    scan_order = (
        [{"job_id": "remote", "score": 56.9, "title": "Staff Engineer", "location": "Remote"}]
        + [{"job_id": f"j{n}", "score": s, "title": f"Job {n}", "location": "Pune"}
           for n, s in enumerate([70.1, 69.5, 69.5, 65.3, 64.5, 64.5, 63.9, 63.9, 63.9,
                                  62.5, 61.5])]
    )
    top = generate.top_ten(scan_order)

    assert len(top) == generate.TOP_N
    assert [j["score"] for j in top] == [70.1, 69.5, 69.5, 65.3, 64.5, 64.5,
                                         63.9, 63.9, 63.9, 62.5]
    assert "remote" not in {j["job_id"] for j in top}, \
        "a 56.9 job must not displace a 62.5 one"


def test_top_ten_keeps_scan_order_within_a_tie():
    """Equal scores must not shuffle, or a re-run analyses a different ten."""
    tied = [{"job_id": f"j{n}", "score": 63.9} for n in range(12)]
    once = [j["job_id"] for j in generate.top_ten(tied)]
    twice = [j["job_id"] for j in generate.top_ten(list(tied))]
    assert once == twice == [f"j{n}" for n in range(10)]


def test_top_ten_survives_a_missing_or_bad_score():
    jobs = [{"job_id": "a"}, {"job_id": "b", "score": None},
            {"job_id": "c", "score": "not a number"}] + \
           [{"job_id": f"j{n}", "score": 50 + n} for n in range(10)]
    top = generate.top_ten(jobs)
    assert len(top) == 10
    assert top[0]["job_id"] == "j9", "the best real score should lead"

# --------------------------------------------------------------------- dedupe

DUPLICATES = [
    # The pair from the spec: two words in common out of seven.
    ("How do you troubleshoot a database connection failure?",
     "What steps would you take when a database connection is not working?"),
    ("What is the Page Object Model?",
     "Explain the Page Object Model pattern."),
    ("Why is CI/CD important for test automation?",
     "What is the purpose of continuous integration in test automation?"),
    ("How do you debug a failing Jenkins build?",
     "What steps would you take when a Jenkins build fails?"),
    ("How would you design a test automation framework from scratch?",
     "How do you structure a test automation framework?"),
    ("What is an implicit wait?", "Define implicit wait."),
]

DISTINCT = [
    # Same tool, different depth - a definition and a design problem.
    ("What is the Page Object Model?",
     "How would you design a Page Object Model framework for a 500-page application?"),
    ("What is Docker?",
     "How do you run a Playwright suite inside Docker containers?"),
    ("What is Kafka?", "How do you test a Kafka consumer end to end?"),
    # Different tools entirely.
    ("What is Selenium WebDriver?", "What is Playwright?"),
    ("What is a REST API?", "What is GraphQL?"),
    ("What is Docker?", "What is Kubernetes?"),
    # Different concepts that share vocabulary.
    ("How do you validate a REST API response schema?",
     "What is JSON schema validation?"),
    ("How would you debug a slow API endpoint?",
     "How do you design a performance test for an API?"),
    ("Explain implicit vs explicit waits in Selenium.",
     "How do you handle dynamic elements in Playwright?"),
    ("How do you test an LLM-backed endpoint?",
     "How do you validate non-deterministic AI output?"),
]


def test_duplicates_are_caught():
    for first, second in DUPLICATES:
        score = dedupe.similarity(first, second)
        assert score >= dedupe.DUPLICATE_AT, \
            f"missed duplicate ({score:.2f}): {first!r} / {second!r}"


def test_distinct_questions_survive():
    for first, second in DISTINCT:
        score = dedupe.similarity(first, second)
        assert score < dedupe.DUPLICATE_AT, \
            f"false duplicate ({score:.2f}): {first!r} / {second!r}"


def test_duplicate_indices_keeps_the_first():
    questions = [
        {"question": "What is the Page Object Model?"},
        {"question": "How do you scale a Selenium grid?"},
        {"question": "Explain the Page Object Model pattern."},
    ]
    doomed = dedupe.duplicate_indices(questions)
    assert doomed == {2}, f"expected the later restatement to be replaced, got {doomed}"


def test_bank_clash_spans_days():
    bank = {"k": {"question": "How do you troubleshoot a database connection failure?"}}
    clash = dedupe.clashes_with_bank(
        "What steps would you take when a database connection is not working?", bank)
    assert clash, "a question already asked on an earlier day should be caught"
    assert dedupe.clashes_with_bank("What is Kubernetes?", bank) is None


def test_intent_separates_definition_from_debugging():
    assert dedupe.intent_of("What is a flaky test?") == "define"
    assert dedupe.intent_of("How do you troubleshoot a flaky test?") == "troubleshoot"
    assert dedupe.intent_of("How would you design a retry strategy?") == "design"
    assert dedupe.intent_of("Difference between smoke and sanity testing?") == "compare"


# --------------------------------------------------------------------- skills

JOBS = [
    {"title": "SDET", "skills": ["Selenium", "Java"],
     "jd_text": "Strong Selenium and Java. CI/CD with Jenkins. REST API testing."},
    {"title": "QA Automation Engineer", "skills": ["Playwright"],
     "jd_text": "Playwright with TypeScript, CI/CD pipelines, REST API automation."},
    {"title": "Test Lead", "skills": [],
     "jd_text": "Own test strategy. Jenkins pipelines. Kubernetes deployments."},
]

PROFILE = {
    "narrative": "Built Playwright automation frameworks and Jenkins pipelines for "
                 "REST API testing of AI inference endpoints.",
    "listed_skills_text": "Languages: Python, SQL. Test Automation: Playwright, Selenium.",
    "key_skills": ["Playwright Automation", "Selenium", "Jenkins"],
    "it_skills": ["Playwright - 1 Year 3 Months"],
    "resume_text": "Playwright Selenium Jenkins Python SQL REST API",
    "skill_years": {"selenium": 5, "jenkins": 3, "playwright": 1.25},
}


def test_matrix_counts_documents_not_mentions():
    rows = {row["skill"]: row for row in skills.matrix(JOBS, PROFILE)}
    assert rows["Jenkins"]["jd_count"] == 2, "Jenkins is named in two of the three JDs"
    assert rows["CI/CD"]["jd_count"] == 2
    assert rows["Kubernetes"]["jd_count"] == 1
    assert all(row["jd_total"] == 3 for row in rows.values())


def test_matrix_grades_evidence_by_where_it_came_from():
    rows = {row["skill"]: row for row in skills.matrix(JOBS, PROFILE)}
    # Described in the experience bullets.
    assert rows["Playwright"]["status"] == "strong"
    # In a skills list only, and under three stated years.
    assert rows["SQL"]["status"] == "moderate" if "SQL" in rows else True
    # Absent from the profile entirely.
    assert rows["Kubernetes"]["status"] == "gap"
    assert rows["Java"]["status"] == "gap"


def test_word_boundaries_hold():
    assert "Java" not in skills.find("We use JavaScript and TypeScript")
    assert "JavaScript" in skills.find("We use JavaScript and TypeScript")
    assert "REST API testing" not in skills.find("A rapid release cadence")


def test_study_order_puts_gaps_ahead_of_strengths():
    rows = skills.matrix(JOBS, PROFILE)
    order = [row["skill"] for row in skills.study_order(rows, 40)]
    assert order.index("Kubernetes") < order.index("Playwright"), \
        "an unmet requirement should outrank one you already have"


# ------------------------------------------------------------------ validation

def _question(number: int, level: str, **overrides) -> dict:
    item = {
        "id": f"Q{number}", "number": number, "level": level,
        "question": f"Unique question {number} about topic {number} in area {number}?",
        "answer": "An answer long enough to clear the minimum length the validator "
                  "insists on, because a one-line answer is not something you can "
                  "study from or repeat in an interview. " * 2,
        "skill": "Playwright", "secondary_skills": [], "jd_numbers": [1],
        "jd_count": 1, "why_asked": "because", "profile_link": "resume link",
    }
    item.update(overrides)
    return item


def _prep(questions: list[dict], **overrides) -> dict:
    prep = {
        "date": "2026-08-25",
        "jobs": [{"jd_text": "x" * 400} for _ in range(10)],
        "skill_matrix": skills.matrix(JOBS, PROFILE),
        "questions": questions,
        "semantic_pass_ran": True,
        "semantic_duplicates": [],
    }
    prep.update(overrides)
    return prep


def _full_set() -> list[dict]:
    questions = []
    number = 0
    for level, count in (("basic", 30), ("intermediate", 40), ("advanced", 30)):
        for _ in range(count):
            number += 1
            questions.append(_question(number, level))
    return questions


def test_counts_are_enforced():
    result = validate.report(_prep(_full_set()))
    by_name = {check["check"]: check for check in result["checks"]}
    assert by_name["exactly 100 questions"]["ok"]
    assert by_name["exactly 30 basic"]["ok"]
    assert by_name["exactly 40 intermediate"]["ok"]
    assert by_name["exactly 30 advanced"]["ok"]

    short = validate.report(_prep(_full_set()[:99]))
    assert not short["ok"]
    assert "exactly 100 questions" in short["failed"]


def test_short_answers_are_flagged_and_repairable():
    questions = _full_set()
    questions[7]["answer"] = "Too short."
    result = validate.report(_prep(questions))
    assert "every question has an answer" in result["failed"]
    assert 7 in validate.repairable(result)


def test_invented_experience_on_a_gap_skill_is_caught():
    questions = _full_set()
    questions[3]["skill"] = "Kubernetes"      # a gap skill in this fixture
    questions[3]["answer"] = ("I have used Kubernetes for three years to run our "
                              "test infrastructure across clusters, and I built the "
                              "Helm charts for the QA namespace myself. " * 2)
    result = validate.report(_prep(questions))
    assert "no unsupported experience is invented" in result["failed"]
    assert 3 in validate.repairable(result)


def test_honest_framing_on_a_gap_skill_passes():
    questions = _full_set()
    questions[3]["skill"] = "Kubernetes"
    questions[3]["answer"] = ("I have not used Kubernetes in production - my container "
                              "experience is Docker. I would come up to speed by mapping "
                              "what I know about container lifecycles onto pods and "
                              "deployments. " * 2)
    result = validate.report(_prep(questions))
    assert "no unsupported experience is invented" not in result["failed"]


def test_first_person_on_a_strong_skill_is_fine():
    questions = _full_set()
    questions[5]["skill"] = "Playwright"      # strong in this fixture
    questions[5]["answer"] = ("I built Playwright frameworks covering UI and API flows, "
                              "and I wired them into Jenkins for nightly runs. " * 3)
    result = validate.report(_prep(questions))
    assert "no unsupported experience is invented" not in result["failed"]


def test_duplicate_questions_fail_validation():
    questions = _full_set()
    questions[0]["question"] = "How do you troubleshoot a database connection failure?"
    questions[1]["question"] = "What steps would you take when a database connection is not working?"
    result = validate.report(_prep(questions))
    assert "no duplicate or near-duplicate questions" in result["failed"]
    assert 1 in validate.repairable(result)


def test_a_question_citing_no_jd_is_flagged():
    questions = _full_set()
    questions[2]["jd_numbers"] = []
    questions[9]["jd_numbers"] = [47]          # out of range
    result = validate.report(_prep(questions))
    assert "questions are relevant to the Top 10 JDs" in result["failed"]
    assert {2, 9} <= validate.repairable(result)


def test_wrong_jd_count_is_fatal():
    result = validate.report(_prep(_full_set(), jobs=[{"jd_text": "x" * 400}] * 9))
    assert "exactly 10 JDs analysed" in result["failed"]


# ------------------------------------------------------------------------ page

def test_qkey_is_stable_across_wording_noise_but_not_meaning():
    assert page.qkey("What is Docker?") == page.qkey("what   is DOCKER?")
    assert page.qkey("What is Docker?") != page.qkey("What is Kubernetes?")


def test_bank_key_does_not_move_when_the_matcher_is_tuned():
    """The bank must survive a change to the dedupe vocabulary.

    It did not, once. The bank was keyed on the concept fingerprint, so adding
    stopwords re-keyed every question ever asked and the file grew a second
    copy of each under its new key - 123 rows for 101 questions, and a
    cross-day duplicate check that silently started missing things.
    """
    question = "How do you troubleshoot a flaky Playwright test in CI?"
    before = dedupe.stable_id(question)

    original = set(dedupe.STOPWORDS)
    try:
        dedupe.STOPWORDS.update({"flaky", "playwright", "ci"})
        assert dedupe.stable_id(question) == before, \
            "the storage key must not depend on the matching vocabulary"
    finally:
        dedupe.STOPWORDS.clear()
        dedupe.STOPWORDS.update(original)

    # The fingerprint, by contrast, is expected to move - that is its job.
    assert dedupe.fingerprint(question) != dedupe.stable_id(question)


def test_bank_compaction_merges_stale_keys():
    from naukri.interview import store

    question = "What is the Page Object Model?"
    stale = {
        "old-fingerprint-key": {"question": question, "answer": "short",
                                "skill": "Playwright", "level": "basic",
                                "first_seen": "2026-08-24", "dates": ["2026-08-24"]},
        dedupe.stable_id(question): {"question": question, "answer": "a much longer answer",
                                     "skill": "Playwright", "level": "basic",
                                     "first_seen": "2026-08-25", "dates": ["2026-08-25"]},
        "orphan": {"answer": "no question at all"},
    }
    merged = {}
    changed = False
    for key, entry in stale.items():
        if not entry.get("question"):
            changed = True
            continue
        proper = dedupe.stable_id(entry["question"])
        changed = changed or proper != key
        merged[proper] = store._merge(merged[proper], entry) if proper in merged else dict(entry)

    assert changed
    assert len(merged) == 1, "both copies of one question should collapse into one row"
    only = next(iter(merged.values()))
    assert only["answer"] == "a much longer answer", "the fuller answer must survive"
    assert only["dates"] == ["2026-08-24", "2026-08-25"], "both days must be kept"
    assert only["first_seen"] == "2026-08-24", "first_seen must stay the earliest"


def test_script_block_cannot_be_broken_out_of():
    payload = page._safe_json({"jd": "</script><script>alert(1)</script>"})
    assert "</script" not in payload
    assert "\\u003c" in payload


def test_template_javascript_parses():
    """The page's script block must be valid JavaScript.

    This exists because it has been broken once. The template used to be a
    normal Python string, so `\\n` inside a JS regex literal was consumed by
    Python and emitted as a real newline - splitting /^\\n+/ across two lines
    and killing the entire script, which renders as a page with zero questions
    on it and no error anywhere the build can see. The template is raw now, and
    this catches the day someone makes it non-raw again.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        return          # nothing to parse with; the render test below still runs

    blocks = re.findall(r"<script>(.*?)</script>", page.TEMPLATE, re.S)
    assert blocks, "the template should carry an inline script block"

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "block.js"
        for index, block in enumerate(blocks):
            path.write_text(block, encoding="utf-8")
            done = subprocess.run([node, "--check", str(path)],
                                  capture_output=True, text=True)
            assert done.returncode == 0, \
                f"script block {index} is not valid JavaScript:\n{done.stderr[:600]}"


def test_answer_formatting_survives_the_template():
    """Fenced code and inline code must reach the browser as markup, not text."""
    assert "```" in page.TEMPLATE, "the fence split should be in the renderer"
    assert "<pre><code>" in page.TEMPLATE
    # The two-character escape, not a real newline - see the test above.
    assert "part.indexOf('\\n')" in page.TEMPLATE
    assert "\n]+)`/g" not in page.TEMPLATE, "a raw newline got into a regex literal"


if __name__ == "__main__":
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception:
            failures += 1
            print(f"  ERROR {test.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


# ------------------------------------------------------- repair index alignment

def _q(level, tag):
    return {"question": f"{tag}?", "answer": "x" * 200, "skill": "Playwright",
            "secondary_skills": [], "jd_numbers": [1], "jd_count": 1,
            "why_asked": "w", "profile_link": "p", "level": level, "reused": False}


def test_assemble_returns_the_same_list_object_it_was_given():
    """prep["questions"] must BE the caller's list, not a sorted copy.

    validate.report() returns indices into prep["questions"], and the repair
    loop overwrites by index in the caller's own list. When _assemble used
    sorted() the two were different objects, and they only agreed while the
    caller's list happened to already be in basic/intermediate/advanced order.

    That stops being true in two ordinary paths: the top-up loop appends a
    basic question after the advanced batches, and the reuse path prepends
    carried b/i/a questions ahead of every generated one. The consequence was
    silent - a flagged question survived, a healthy one at the same index was
    destroyed, and the 30/40/30 counts stayed intact so no check noticed.
    """
    # Deliberately interleaved, the way reuse + top-up actually leaves it.
    questions = [_q("basic", "carried-b"), _q("advanced", "carried-a"),
                 _q("intermediate", "carried-i"), _q("advanced", "gen-a"),
                 _q("basic", "gen-b"), _q("basic", "topup-b")]

    prep = generate._assemble(
        "2026-08-25", "2026-08-25-r1", [{"jd_text": "x" * 400}] * 10,
        {"name": "n", "designation": "d", "total_years": 6, "resume_path": None},
        [], {"strong": [], "moderate": [], "gap": []}, {}, {}, [],
        questions, {}, [], "claude-cli", None, [], True, {})

    assert prep["run_id"] == "2026-08-25-r1" and prep["run"] == 1

    assert prep["questions"] is questions, \
        "_assemble must sort in place; a copy desynchronises repair from validation"
    assert [q["level"] for q in questions] == \
        ["basic", "basic", "basic", "intermediate", "advanced", "advanced"]

    # The invariant that actually matters: an index from the validated prep
    # addresses the same object in the list _repair will mutate.
    for index, question in enumerate(prep["questions"]):
        assert questions[index] is question


def test_normalise_does_not_invent_a_jd_citation():
    """An uncited question must stay uncited, or the gate can never fire."""
    item = {"question": "What is Docker?", "answer": "y" * 200, "skill": "Docker"}
    out = generate._normalise(item, "basic", 10, [])
    assert out["jd_numbers"] == [], "no synthesised JD1"
    assert out["jd_count"] == 0

    prep = _prep([_q("basic", f"u{n}") for n in range(100)])
    prep["questions"][3]["jd_numbers"] = []
    result = validate.report(prep)
    assert "questions are relevant to the Top 10 JDs" in result["failed"], \
        "the relevance check must be able to fail"
    assert 3 in validate.repairable(result)


# ----------------------------------------------------------------- run slots

def test_run_ids_split_and_sort_by_day_then_run():
    from naukri.interview import store

    assert store.run_id("2026-08-26", 3) == "2026-08-26-r3"
    assert store.split_run("2026-08-26-r3") == ("2026-08-26", 3)
    # A file written before run ids existed reads as run 1, not as a crash.
    assert store.split_run("2026-08-26") == ("2026-08-26", 1)

    stamps = ["2026-08-25-r2", "2026-08-26-r1", "2026-08-25-r10", "2026-08-25-r1"]
    assert sorted(stamps, key=store._sort_key, reverse=True) == [
        "2026-08-26-r1", "2026-08-25-r10", "2026-08-25-r2", "2026-08-25-r1"], \
        "run 10 must sort above run 2, so the picker is not lexicographic"


def test_run_slot_numbering_is_not_lexicographic():
    """r10 must follow r9, not sort between r1 and r2."""
    from naukri.interview import store
    runs = [store.split_run(s)[1] for s in
            sorted([store.run_id("2026-08-26", n) for n in range(1, 12)],
                   key=store._sort_key, reverse=True)]
    assert runs == list(range(11, 0, -1))


def test_jd_text_carries_across_runs_of_the_same_day(tmp_path=None):
    """A JD does not change between 08:52 and 13:23.

    Refetching all ten every run is three times the browsing for identical
    text, which is exactly the pattern that gets a Naukri session blocked.
    """
    top = [{"job_id": "a", "title": "SDET"}, {"job_id": "b", "title": "QA"}]
    cached = {"job_id": "a", "title": "SDET", "jd_text": "x" * 900,
              "jd_source": "jobapi/v4", "jd_extras": {"role": "SDET"}}

    import naukri.interview.store as store
    real_runs, real_load = store.runs_for, store.load_prep
    store.runs_for = lambda day: ["2026-08-26-r1"]
    store.load_prep = lambda stamp: {"jobs": [cached]}
    try:
        out = generate._reuse_jd_text(top, "2026-08-26", force=False)
    finally:
        store.runs_for, store.load_prep = real_runs, real_load

    assert out[0]["jd_text"] == cached["jd_text"], "the repeated job reuses its text"
    assert out[0]["jd_extras"] == {"role": "SDET"}
    assert not out[1].get("jd_text"), "the new job is left for the fetcher"
    assert out[0] is not cached, "the cache must not be mutated by the caller"
