"""Detect duplicate questions, including ones that share no wording.

Rule 4 is the hard one. Plain text similarity does not solve it - the spec's
own example is a pair that overlaps on two words out of seven:

    "How do you troubleshoot a database connection failure?"
    "What steps would you take when a database connection is not working?"

Jaccard on those tokens is 0.29, which is nowhere near any threshold you could
also use safely. So the comparison is not on words. Every question is reduced
to a *concept key* of two parts:

    intent    what is being asked for - define, troubleshoot, compare,
              design, mechanism, tradeoff, experience...
    subject   the content words, lemmatised and folded through a synonym map
              so "failure", "not working" and "breaks" are one token

On the pair above both reduce to (troubleshoot, {database, connection, fail}),
which is an exact match. That catches reworded duplicates cheaply and
deterministically, before any model is asked - and what it misses (two
genuinely different phrasings of one idea that share no vocabulary at all) is
what the semantic pass in generate.py is for.

Nothing here ever silently drops a question. `find_duplicates` reports pairs;
deciding what to do about them belongs to the caller, which needs to
regenerate rather than end up with 97.
"""
from __future__ import annotations

import hashlib
import re
from itertools import combinations

# Question stems that mean the same thing. Longest first - "what steps would
# you take" must be tested before the bare "what".
INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("troubleshoot", (
        "how (do|would|will) you (troubleshoot|debug|diagnose|investigate|fix|resolve|handle)",
        "what steps would you take", "what would you do (if|when)", "how do you approach.*(issue|problem|failure)",
        "walk me through (how you|debugging|troubleshooting)", "how (do|would) you root cause",
        "what is your approach (to|when).*(fail|debug|flak|break|issue)",
        "how (do|would) you deal with", "how (do|would) you find out why",
    )),
    ("compare", (
        "difference between", "compare", "versus", " vs ", "when would you (use|choose|pick).*(over|instead of|rather than)",
        "which (one|is better)", "trade.?off between",
    )),
    ("design", (
        "how would you (design|architect|structure|build|implement|set up|organise|organize|create)",
        "design a", "architect a", "how do you build", "how do you structure",
        "what would your .*(framework|architecture|strategy|design|approach) look like",
    )),
    ("mechanism", (
        "how does .* work", "how is .* implemented", "what happens (when|if|under the hood)",
        "explain how .* works", "under the hood", "how does .* handle",
    )),
    ("tradeoff", (
        "trade.?off", "pros and cons", "advantages and disadvantages", "limitations of",
        "why (would you )?not", "when (would|should) you avoid", "downside",
    )),
    ("experience", (
        "tell me about a time", "describe a (time|situation|project)", "have you ever",
        "give an example (of|from) your", "in your experience", "on your resume",
        "walk me through a project",
    )),
    ("rationale", (
        "^why ", " why (is|are|do|does|would|should)", "what is the (point|purpose|benefit|value) of",
        "why (is|are|do|does) .* important",
    )),
    ("measure", (
        "how (do|would) you (measure|quantify|track|monitor|report|validate|verify|assess|evaluate)",
        "what metrics", "how (do|would) you know (if|that|whether)", "what would you check",
    )),
    ("define", (
        "^what (is|are)", "^define ", "^explain ", "^describe ", "what do you (mean|understand) by",
        "what does .* stand for", "^name ",
    )),
]

# Words that carry no concept. Question scaffolding, mostly.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "for", "of", "with",
    "from", "by", "as", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "you", "your", "yours", "we", "our", "i", "me", "my", "it", "its", "they", "them", "their",
    "this", "that", "these", "those", "there", "here", "what", "which", "who", "whom", "when",
    "where", "why", "how", "can", "could", "would", "should", "will", "shall", "may", "might",
    "must", "have", "has", "had", "not", "no", "so", "than", "then", "too", "very", "just",
    "about", "into", "over", "under", "between", "through", "during", "before", "after",
    "above", "below", "up", "down", "out", "off", "again", "further", "once", "any", "some",
    "such", "only", "own", "same", "each", "few", "more", "most", "other", "another", "both",
    "all", "one", "two", "give", "explain", "describe", "tell", "walk", "take", "steps", "step",
    "approach", "way", "ways", "example", "examples", "mean", "means", "make", "makes", "get",
    "gets", "use", "used", "using", "uses", "like", "want", "need", "know", "think", "say",
    "situation", "case", "cases", "scenario", "time", "times", "point", "thing", "things",
    "please", "also", "well", "good", "best", "better", "new", "old", "different", "important",
    # The verbs that signal the intent. The intent is already the first half of
    # the concept key, so leaving these in the subject counts them twice and
    # pushes two phrasings of one design question apart: "how would you DESIGN
    # a framework from SCRATCH" against "how do you STRUCTURE a framework"
    # shares three subject words and differs on three verbs, which reads as a
    # weaker match than it is.
    "design", "designing", "architect", "structure", "structuring", "organise", "organize",
    "implement", "implementing", "build", "building", "create", "creating", "set", "setup",
    "troubleshoot", "troubleshooting", "debug", "debugging", "diagnose", "investigate",
    "fix", "fixing", "resolve", "resolving", "handle", "handling", "deal", "dealing",
    "compare", "define", "defining", "measure", "evaluate", "assess", "scratch",
}

# Different words for the same idea, folded to one token. This is where
# "not working", "failure" and "breaks" become the same concept.
SYNONYMS = {
    # failure family
    "failure": "fail", "failing": "fail", "fails": "fail", "failed": "fail",
    "broken": "fail", "breaks": "fail", "breaking": "fail", "break": "fail",
    "error": "fail", "errors": "fail", "issue": "fail", "issues": "fail",
    "problem": "fail", "problems": "fail", "crash": "fail", "crashes": "fail",
    "down": "fail", "unavailable": "fail", "outage": "fail", "wrong": "fail",
    "working": "fail", "unstable": "fail", "unreliable": "fail",
    # flakiness
    "flaky": "flake", "flakiness": "flake", "flakey": "flake", "intermittent": "flake",
    "unstable_test": "flake", "nondeterministic": "flake", "non": "", "deterministic": "determinism",
    # testing vocabulary
    "test": "test", "tests": "test", "testing": "test", "tested": "test", "tester": "test",
    "automation": "automate", "automated": "automate", "automating": "automate",
    "automate": "automate", "script": "automate", "scripts": "automate", "scripting": "automate",
    "framework": "framework", "frameworks": "framework",
    "suite": "suite", "suites": "suite",
    "case": "testcase", "cases": "testcase",
    "assertion": "assert", "assertions": "assert", "asserts": "assert", "verify": "assert",
    "validation": "assert", "validate": "assert", "validating": "assert", "check": "assert",
    "defect": "defect", "defects": "defect", "bug": "defect", "bugs": "defect",
    "regression": "regression", "regressions": "regression",
    "coverage": "coverage", "covered": "coverage",
    # pipeline
    "pipeline": "pipeline", "pipelines": "pipeline", "build": "pipeline", "builds": "pipeline",
    "cicd": "cicd", "ci": "cicd", "cd": "cicd",
    "deployment": "deploy", "deploy": "deploy", "deployed": "deploy", "release": "deploy",
    "releases": "deploy",
    # api / web
    "api": "api", "apis": "api", "endpoint": "api", "endpoints": "api",
    "request": "request", "requests": "request", "response": "response", "responses": "response",
    "service": "service", "services": "service", "microservice": "microservice",
    "microservices": "microservice",
    # data
    "database": "database", "databases": "database", "db": "database", "sql": "sql",
    "query": "query", "queries": "query",
    "connection": "connection", "connections": "connection", "connectivity": "connection",
    "connect": "connection", "connecting": "connection",
    # perf
    "performance": "performance", "slow": "performance", "slowness": "performance",
    "latency": "performance", "throughput": "performance", "speed": "performance",
    "optimise": "optimise", "optimize": "optimise", "optimisation": "optimise",
    "optimization": "optimise", "tuning": "optimise", "tune": "optimise",
    "scalability": "scale", "scaling": "scale", "scale": "scale",
    # element / locator
    "locator": "locator", "locators": "locator", "selector": "locator", "selectors": "locator",
    "element": "element", "elements": "element",
    "wait": "wait", "waits": "wait", "waiting": "wait", "timeout": "wait", "timeouts": "wait",
    "synchronisation": "wait", "synchronization": "wait", "sync": "wait",
    # people/process
    "team": "team", "teams": "team", "stakeholder": "stakeholder", "stakeholders": "stakeholder",
    "manager": "stakeholder", "developer": "developer", "developers": "developer", "dev": "developer",
    "review": "review", "reviews": "review", "reviewing": "review",
    "strategy": "strategy", "strategies": "strategy", "plan": "strategy", "planning": "strategy",
    "report": "report", "reporting": "report", "reports": "report",
    "environment": "environment", "environments": "environment", "env": "environment",
    "container": "container", "containers": "container", "containerised": "container",
    "parallel": "parallel", "parallelism": "parallel", "concurrent": "parallel",
    "concurrency": "parallel",
    "data": "data", "dataset": "data", "datasets": "data",
    "mock": "mock", "mocks": "mock", "mocking": "mock", "stub": "mock", "stubs": "mock",
    "stubbing": "mock", "virtualisation": "mock", "virtualization": "mock",
    "model": "model", "models": "model", "llm": "llm", "llms": "llm",
    "prompt": "prompt", "prompts": "prompt",
    "agent": "agent", "agents": "agent", "agentic": "agent",
}

# Multi-word idioms folded to one token before the text is split. Splitting
# first loses them: "continuous integration" becomes {continuous, integration},
# which shares nothing with "CI/CD" even though they are the same subject.
PHRASES: list[tuple[str, str]] = [
    ("continuous integration and continuous delivery", "cicd"),
    ("continuous integration", "cicd"),
    ("continuous delivery", "cicd"),
    ("continuous deployment", "cicd"),
    ("ci/cd", "cicd"),
    ("ci cd", "cicd"),
    ("build pipeline", "cicd pipeline"),
    ("page object model", "pom"),
    ("page objects", "pom"),
    ("page object", "pom"),
    ("root cause analysis", "rootcause"),
    ("root cause", "rootcause"),
    ("test case", "testcase"),
    ("test cases", "testcase"),
    ("test data", "testdata"),
    ("flaky test", "flake test"),
    ("flaky tests", "flake test"),
    ("fail intermittently", "flake fail"),
    ("fails intermittently", "flake fail"),
    ("intermittent failure", "flake fail"),
    ("intermittently fail", "flake fail"),
    ("pass and fail", "flake"),
    ("not working", "fail"),
    ("does not work", "fail"),
    ("doesn't work", "fail"),
    ("stops working", "fail"),
    ("won't start", "fail"),
    ("quality assurance", "qa"),
    ("software development engineer in test", "sdet"),
    ("rest api", "api"),
    ("restful api", "api"),
    ("web service", "api"),
    ("json schema", "schema"),
    ("shift left", "shiftleft"),
    ("shift-left", "shiftleft"),
    ("test driven development", "tdd"),
    ("behaviour driven development", "bdd"),
    ("behavior driven development", "bdd"),
    ("response time", "performance"),
    ("load test", "performance test"),
    ("stress test", "performance test"),
    ("machine learning", "ml"),
    ("large language model", "llm"),
    ("model context protocol", "mcp"),
    ("computer vision", "cv"),
    ("pull request", "review"),
    ("code coverage", "coverage"),
    ("defect leakage", "defect leak"),
]

_PLURAL = re.compile(r"(?<=\w)(?:ies|es|s)$")


def _lemma(word: str) -> str:
    if word in SYNONYMS:
        return SYNONYMS[word]
    stripped = _PLURAL.sub("", word)
    if stripped != word and len(stripped) > 2:
        return SYNONYMS.get(stripped, stripped)
    return word


def intent_of(question: str) -> str:
    low = " " + re.sub(r"\s+", " ", (question or "").strip().lower()) + " "
    for name, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, low):
                return name
    return "define"


def subject_of(question: str) -> frozenset[str]:
    """The content words of a question, lemmatised and folded."""
    low = " " + re.sub(r"\s+", " ", (question or "").lower()) + " "
    # Fold multi-word idioms first - see PHRASES for why order matters.
    for phrase, replacement in PHRASES:
        if phrase in low:
            low = low.replace(phrase, replacement)
    low = re.sub(r"[^a-z0-9+#/. ]+", " ", low)
    words = [w.strip(".") for w in low.split()]
    out = set()
    for word in words:
        if not word or word in STOPWORDS or len(word) < 2:
            continue
        lemma = _lemma(word)
        if lemma and lemma not in STOPWORDS and len(lemma) > 1:
            out.add(lemma)
    return frozenset(out)


def concept_key(question: str) -> tuple[str, frozenset[str]]:
    return intent_of(question), subject_of(question)


def fingerprint(question: str) -> str:
    """A string form of the concept key. For reporting, NOT for storage.

    This changes whenever the stopword list or the synonym map changes, which
    is exactly what you want from a matcher and exactly what you do not want
    from a database key - see stable_id.
    """
    intent, subject = concept_key(question)
    return intent + "|" + ",".join(sorted(subject))


def stable_id(question: str) -> str:
    """A permanent id for a question, derived only from its text.

    The question bank is keyed on this rather than on `fingerprint`. Tuning the
    synonym map re-fingerprints every question ever asked, and a bank keyed on
    fingerprints answers that by storing all of them a second time under the new
    keys - 123 rows for 101 questions, and a "have I asked this before?" check
    that quietly starts saying no.
    """
    normalised = " ".join(re.sub(r"[^a-z0-9 ]+", " ", (question or "").lower()).split())
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:12]


def score_keys(key_a: tuple[str, frozenset[str]],
               key_b: tuple[str, frozenset[str]]) -> float:
    """0-1 concept overlap between two concept keys.

    Half Jaccard, half overlap coefficient. Jaccard alone is wrong here
    because phrase folding makes subjects different *sizes*: "What is the
    Page Object Model?" reduces to {pom} and "Explain the Page Object Model
    pattern." to {pom, pattern}, and Jaccard calls that 0.5 - two questions
    with literally the same subject, scored as barely related. The overlap
    coefficient sees the containment and calls it 1.0; averaging the two
    keeps that signal without letting every one-word subject swallow every
    longer question that happens to mention it.
    """
    intent_a, subject_a = key_a
    intent_b, subject_b = key_b
    if not subject_a or not subject_b:
        return 0.0
    shared = len(subject_a & subject_b)
    if not shared:
        return 0.0
    jaccard = shared / len(subject_a | subject_b)
    containment = shared / min(len(subject_a), len(subject_b))
    score = 0.5 * jaccard + 0.5 * containment
    # Asking for a definition and asking how to debug the same thing are
    # different questions, so a mismatched intent has to cost real ground.
    return score if intent_a == intent_b else score * 0.55


def similarity(a: str, b: str) -> float:
    """0-1 concept overlap. 1.0 means the same question in different words."""
    return score_keys(concept_key(a), concept_key(b))


DUPLICATE_AT = 0.72


def find_duplicates(questions: list[dict], threshold: float = DUPLICATE_AT) -> list[dict]:
    """Every pair scoring at or above `threshold`, worst first.

    Reports the *later* question as the one to replace, so a caller walking
    the list keeps the first statement of each concept.
    """
    texts = [(index, item.get("question") or "") for index, item in enumerate(questions)]
    keys = {index: concept_key(text) for index, text in texts}

    pairs = []
    for (index_a, text_a), (index_b, text_b) in combinations(texts, 2):
        score = score_keys(keys[index_a], keys[index_b])
        if score >= threshold:
            pairs.append({
                "keep": index_a,
                "replace": index_b,
                "score": round(score, 3),
                "keep_question": text_a,
                "replace_question": text_b,
                "shared": sorted(keys[index_a][1] & keys[index_b][1]),
            })
    pairs.sort(key=lambda p: -p["score"])
    return pairs


def duplicate_indices(questions: list[dict], threshold: float = DUPLICATE_AT) -> set[int]:
    """Indices to regenerate so that no concept is asked about twice.

    Walks the list in order and keeps the first question of each concept, so
    the survivors are stable across runs rather than depending on which half
    of a pair the scorer happened to look at first.
    """
    seen: list[tuple[str, frozenset[str]]] = []
    doomed = set()
    for index, item in enumerate(questions):
        key = concept_key(item.get("question") or "")
        if not key[1]:
            continue
        if any(score_keys(key, other) >= threshold for other in seen):
            doomed.add(index)
        else:
            seen.append(key)
    return doomed


def clashes_with_bank(question: str, bank: dict, threshold: float = DUPLICATE_AT) -> str | None:
    """The banked question this one duplicates, or None.

    Keeps rule 4 true across days: without it, every morning's run
    re-derives the same obvious question from the same recurring skill.
    """
    key = concept_key(question)
    if not key[1]:
        return None
    for entry in bank.values():
        other = entry.get("question") or ""
        if score_keys(key, concept_key(other)) >= threshold:
            return other
    return None
