"""The pipeline: Top 10 -> full JDs -> analysis -> 100 questions -> validation.

Shape of a run:

    scan results      data/jobs/results-<date>.json, already scored
    top 10            the highest-scoring Naukri jobs, re-sorted by score here
                      rather than taken in the order the scan wrote them
    full JDs          one navigation each - the scan only has teasers
    skill matrix      computed here, by term matching, not by the model
    analysis          one model call: target profile, per-JD read, gap analysis
    questions         six model calls, batched by level
    dedupe            concept keys first, then one model call for what that missed
    repair            replace only what failed, up to three rounds
    validate          the §13 gate
    write             prep-<date>.json, then the HTML page

Batching the question generation is not an optimisation. One call for a hundred
questions produces a list that sags in the middle - the model loses track of
what it has already asked around question forty and starts rewording. Six calls
of fifteen to twenty, each handed the full text of everything written so far,
keeps every batch aware of the whole corpus.

LinkedIn cards are not eligible for the Top 10: they carry no description text
and no 0-100 score, so a LinkedIn "JD" would contribute a title and nothing to
analyse. The Top 10 is the Naukri top 10, which is what the scan reports too.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from . import dedupe, engine as engine_mod, jdfetch, prompts, skills, store, validate
from . import profile as profile_mod

log = logging.getLogger("naukri.interview.generate")

TOP_N = 10
BATCHES = [("basic", 15), ("basic", 15),
           ("intermediate", 20), ("intermediate", 20),
           ("advanced", 15), ("advanced", 15)]
MAX_REPAIR_ROUNDS = 3
REUSE_SIMILARITY = 0.75      # below this, yesterday's questions are not reused
REUSE_SHARE = 0.5            # at most half of a level may come from the bank


class GenerationError(RuntimeError):
    """The run could not produce a usable preparation set."""


# ----------------------------------------------------------------- normalising

def _infer_skill(question: str, answer: str, matrix: list[dict] | None) -> str:
    """The best skill tag for a question whose own tag is missing.

    A repair call occasionally returns just the question and answer. Falling
    back to a literal "General" makes the question unfilterable on the page and
    fails the coverage check for no good reason, when the skill is sitting in
    the question text waiting to be matched. Prefer the skill the JDs want most
    among those the text actually names.
    """
    hits = skills.find(question + "\n" + answer)
    if not hits:
        return "General"
    demand = {row["skill"]: row["jd_count"] for row in (matrix or [])}
    return max(hits, key=lambda name: (demand.get(name, 0), name in question))


def _normalise(item: dict, level: str, job_count: int,
               matrix: list[dict] | None = None) -> dict | None:
    question = (item.get("question") or "").strip()
    answer = (item.get("answer") or "").strip()
    if not question or not answer:
        return None
    numbers = []
    for raw in item.get("jd_numbers") or []:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= job_count and number not in numbers:
            numbers.append(number)
    secondary = [s.strip() for s in (item.get("secondary_skills") or [])
                 if isinstance(s, str) and s.strip()]
    return {
        "question": question,
        "answer": answer,
        "skill": ((item.get("skill") or "").strip()
                  or _infer_skill(question, answer, matrix)),
        "secondary_skills": secondary[:4],
        # NOT `numbers or [1]`. Substituting JD1 for "the model cited nothing"
        # invents a citation and, worse, makes validate.py's relevance check
        # structurally incapable of failing - every question would leave here
        # with a non-empty in-range list and the gate would print a guaranteed
        # PASS. An empty list is the honest answer; the page suppresses the
        # badge for it and the gate flags it for regeneration.
        "jd_numbers": numbers,
        "jd_count": len(numbers),
        "why_asked": (item.get("why_asked") or "").strip(),
        "profile_link": (item.get("profile_link") or "").strip(),
        "level": level,
        "reused": False,
    }


def _score_of(job: dict) -> float:
    try:
        return float(job.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def top_ten(naukri: list[dict]) -> list[dict]:
    """The ten highest-scoring jobs, re-sorted rather than taken as written.

    The scan does not store its jobs in score order. Under --worldwide it sorts
    remote-first and score second, so results-<date>.json can lead with a job
    that scored well below the tenth-best - on 2026-08-25 a 56.9 remote role sat
    at the top and pushed a 62.5 out of the ten entirely.

    That ordering is right for a list you are going to apply from: you want
    remote roles in front of you. It is wrong for choosing what to study, where
    the only question is which ten postings best match you. So the ranking is
    re-derived here instead of inherited, and the caller logs anything the
    scan's own order would have included.

    Ties keep the scan's relative order, which keeps a re-run on unchanged data
    producing the same ten.
    """
    return sorted(naukri, key=_score_of, reverse=True)[:TOP_N]


def _reuse_jd_text(top: list[dict], day: str, force: bool) -> list[dict]:
    """Fill jd_text from earlier runs of the same day where the job repeats.

    `force` (--reuse-jds) additionally accepts text from any earlier day, which
    is what you want when re-running an analysis without wanting ten more
    navigations. Without it, only the same day's runs are trusted: a posting
    can be edited overnight, and a stale JD is a wrong study page.
    """
    stamps = store.runs_for(day) if not force else store.prep_runs()
    cache: dict[str, dict] = {}
    for stamp in stamps:
        prep = store.load_prep(stamp)
        for job in (prep or {}).get("jobs") or []:
            key = str(job.get("job_id"))
            if key and key not in cache and (job.get("jd_text") or "").strip():
                cache[key] = job

    out, hits = [], 0
    for job in top:
        cached = cache.get(str(job.get("job_id")))
        if cached:
            merged = dict(job)
            for field in ("jd_text", "jd_source", "jd_extras"):
                if cached.get(field):
                    merged[field] = cached[field]
            out.append(merged)
            hits += 1
        else:
            out.append(dict(job))
    if hits:
        log.info("Reused JD text for %d of %d job(s) from an earlier run", hits, len(top))
    return out


def _mtime(path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(
            timespec="seconds")
    except OSError:
        return None


def _under_covered(questions: list[dict], matrix: list[dict], limit: int = 8) -> list[str]:
    """High-demand skills with the fewest questions so far."""
    counts: dict[str, int] = {}
    for question in questions:
        for skill in [question.get("skill")] + (question.get("secondary_skills") or []):
            if skill:
                counts[skill.strip().lower()] = counts.get(skill.strip().lower(), 0) + 1
    ranked = sorted(
        (row for row in matrix if row["importance"] in ("Critical", "High", "Medium")),
        key=lambda row: (counts.get(row["skill"].lower(), 0),
                         -row["jd_count"]))
    return [row["skill"] for row in ranked[:limit]
            if counts.get(row["skill"].lower(), 0) < 3]


# --------------------------------------------------------------------- reuse

def _reusable(bank: dict, matrix: list[dict], previous: dict | None) -> dict[str, list[dict]]:
    """Bank questions still relevant to today's skills, grouped by level."""
    if not previous:
        return {}

    today_skills = {row["skill"].lower() for row in matrix}
    previous_skills = {row["skill"].lower() for row in (previous.get("skill_matrix") or [])}
    if not previous_skills:
        return {}

    overlap = len(today_skills & previous_skills) / len(today_skills | previous_skills)
    if overlap < REUSE_SIMILARITY:
        log.info("Top 10 skills only %.0f%% similar to %s - generating fresh",
                 overlap * 100, previous.get("date"))
        return {}

    log.info("Top 10 skills %.0f%% similar to %s - reusing what still applies",
             overlap * 100, previous.get("date"))

    pool: dict[str, list[dict]] = {"basic": [], "intermediate": [], "advanced": []}
    for entry in bank.values():
        level = entry.get("level")
        if level not in pool:
            continue
        if (entry.get("skill") or "").lower() not in today_skills:
            continue
        if len((entry.get("answer") or "").strip()) < validate.MIN_ANSWER_CHARS:
            continue
        pool[level].append(entry)
    return pool


def _carry_over(previous: dict, pool: dict, matrix: list[dict],
                job_count: int) -> list[dict]:
    """Take the reusable questions forward, capped and re-linked to today's JDs."""
    if not pool:
        return []

    today_skills = {row["skill"].lower(): row for row in matrix}
    by_question = {q["question"]: q for q in (previous.get("questions") or [])}

    carried: list[dict] = []
    for level, entries in pool.items():
        cap = int(validate.TARGET[level] * REUSE_SHARE)
        # Prefer questions on skills that are still in heavy demand.
        entries = sorted(entries, key=lambda e: -(
            today_skills.get((e.get("skill") or "").lower(), {}).get("jd_count", 0)))
        for entry in entries[:cap]:
            original = by_question.get(entry["question"]) or {}
            item = _normalise({
                "question": entry["question"],
                "answer": entry["answer"],
                "skill": entry.get("skill"),
                "secondary_skills": original.get("secondary_skills") or [],
                # The old JD numbers point at yesterday's postings, so they are
                # dropped and re-derived below rather than shown as if they
                # referred to today's ten.
                "jd_numbers": [],
                "why_asked": original.get("why_asked"),
                "profile_link": original.get("profile_link"),
            }, level, job_count, matrix)
            if item:
                item["reused"] = True
                item["reused_from"] = entry.get("first_seen")
                carried.append(item)
    log.info("Carried %d question(s) forward from the bank", len(carried))
    return carried


def _relink(questions: list[dict], jobs: list[dict]) -> None:
    """Re-derive jd_numbers for carried questions against today's ten JDs."""
    per_job = [skills.find(skills.job_text(job)) for job in jobs]
    for question in questions:
        if not question.get("reused"):
            continue
        wanted = {(question.get("skill") or "").lower()} | \
                 {s.lower() for s in question.get("secondary_skills") or []}
        numbers = [index + 1 for index, hits in enumerate(per_job)
                   if any(hit.lower() in wanted for hit in hits)]
        # Same honesty rule as _normalise: no synthesised JD1. A carried
        # question whose skill no longer appears in any of today's ten has
        # genuinely lost its link, and the gate should say so.
        question["jd_numbers"] = numbers
        question["jd_count"] = len(numbers)


# ---------------------------------------------------------------- the pipeline

def run(day: str | None = None, engine: str | None = None, model: str | None = None,
        headless: bool = False, reuse_jds: bool = False,
        no_reuse: bool = False, run: int | None = None) -> dict:
    """Build a preparation set for one scan. Returns the prep dict.

    `run` picks the slot within the day; the default claims the next free one.
    The scan fires three times a day and rewrites results-<date>.json each
    time, so each run is a different Top 10 and gets its own permanent file
    rather than overwriting the one you were studying from.
    """
    day = day or date.today().isoformat()
    stamp = store.run_id(day, run if run is not None else store.next_run(day))
    engine = engine or engine_mod.default_engine()
    log.info("Preparation run %s", stamp)

    results = store.load_results(day)
    naukri = results.get("naukri") or []
    if len(naukri) < TOP_N:
        raise GenerationError(
            f"The scan for {day} found only {len(naukri)} Naukri job(s); "
            f"{TOP_N} are needed for the Top 10 analysis.\n"
            f"  Widen the scan:  python main.py --jobs-export --worldwide --top 60")

    top = top_ten(naukri)
    log.info("Top %d for %s, by score:", TOP_N, day)
    for index, job in enumerate(top, start=1):
        log.info("  %2d. %5.1f  %-44s %s", index, _score_of(job),
                 (job.get("title") or "")[:44], (job.get("company") or "")[:26])

    # Say so when the scan's own ordering would have picked a different ten, so
    # a page that disagrees with the morning's terminal output is explained
    # rather than mysterious.
    displaced = [job for job in naukri[:TOP_N]
                 if job.get("job_id") not in {j.get("job_id") for j in top}]
    for job in displaced:
        log.info("  (not analysed: %s, %.1f - ranked into the scan's top ten by "
                 "its remote-first display order, not by score)",
                 (job.get("title") or "")[:44], _score_of(job))

    profile = profile_mod.load()
    log.info("Profile: %s, %s years, resume %d chars",
             profile["name"], profile["total_years"], len(profile["resume_text"]))

    # --- full JDs
    #
    # An earlier run of the same day usually shares most of its Top 10, and a
    # JD does not change between 08:52 and 13:23. Carrying the fetched text
    # across saves ten browser navigations per run and, more to the point,
    # keeps three runs a day from looking like a scraper to Naukri.
    jobs = _reuse_jd_text(top, day, reuse_jds)
    missing = [job for job in jobs if not job.get("jd_text")]
    if missing:
        fetched = {j.get("job_id"): j for j in jdfetch.fetch(missing, headless=headless)}
        jobs = [fetched.get(job.get("job_id"), job) for job in jobs]

    matrix = skills.matrix(jobs, profile)
    bucketed = skills.buckets(matrix)
    log.info("Skill matrix: %d skills - %d strong, %d moderate, %d gap",
             len(matrix), len(bucketed["strong"]), len(bucketed["moderate"]),
             len(bucketed["gap"]))

    brief = profile_mod.brief(profile)
    calls: list[dict] = []

    # --- collective analysis
    log.info("Analysing the ten JDs collectively")
    analysis, meta = engine_mod.ask_json(
        prompts.analysis_prompt(brief, jobs, matrix),
        engine=engine, model=model, label="collective analysis")
    calls.append(meta)

    target_profile = analysis.get("target_profile") or {}
    gap_analysis = analysis.get("gap_analysis") or {}
    priority = analysis.get("priority_topics") or [row["skill"] for row in
                                                   skills.study_order(matrix, 12)]

    # Fold the model's per-JD read back onto the job records.
    for entry in analysis.get("jobs") or []:
        try:
            index = int(entry.get("jd", 0)) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(jobs):
            jobs[index]["summary"] = entry.get("summary") or ""
            jobs[index]["key_requirements"] = entry.get("key_requirements") or []
            jobs[index]["key_skills"] = entry.get("key_skills") or []
            jobs[index]["fit_note"] = entry.get("fit_note") or ""

    # --- reuse, then generate the remainder
    #
    # Compare against the previous RUN, not the previous day. Runs four hours
    # apart share most of their Top 10, so the similarity gate opens and most
    # of the corpus carries over; runs a day apart usually do not - the first
    # day-2 run measured 62% and correctly generated fresh. That is also what
    # keeps three runs a day affordable: only the first pays full price.
    bank = store.load_bank()
    previous_runs = [s for s in store.prep_runs() if s != stamp]
    previous = store.load_prep(previous_runs[0]) if previous_runs else None
    pool = {} if no_reuse else _reusable(bank, matrix, previous)
    questions = _carry_over(previous, pool, matrix, len(jobs)) if pool else []
    _relink(questions, jobs)

    have = {level: sum(1 for q in questions if q["level"] == level)
            for level in validate.TARGET}

    for level, size in BATCHES:
        shortfall = validate.TARGET[level] - have[level]
        if shortfall <= 0:
            continue
        want = min(size, shortfall)
        avoid = [q["question"] for q in questions]
        log.info("Generating %d %s question(s) (%d/%d for this level)",
                 want, level, have[level], validate.TARGET[level])
        payload, meta = engine_mod.ask_json(
            prompts.questions_prompt(level, want, brief, jobs, matrix, priority,
                                     avoid, focus=_under_covered(questions, matrix),
                                     target_profile=target_profile),
            engine=engine, model=model, label=f"{level} x{want}")
        calls.append(meta)
        for item in payload.get("questions") or []:
            normalised = _normalise(item, level, len(jobs), matrix)
            if normalised:
                questions.append(normalised)
                have[level] += 1

    # --- top up any level a batch came up short on
    for level, wanted in validate.TARGET.items():
        rounds = 0
        while have[level] < wanted and rounds < 3:
            rounds += 1
            short = wanted - have[level]
            log.info("Topping up %s: %d short", level, short)
            payload, meta = engine_mod.ask_json(
                prompts.questions_prompt(level, short, brief, jobs, matrix, priority,
                                         [q["question"] for q in questions],
                                         focus=_under_covered(questions, matrix),
                                         target_profile=target_profile),
                engine=engine, model=model, label=f"{level} top-up x{short}")
            calls.append(meta)
            added = 0
            for item in payload.get("questions") or []:
                normalised = _normalise(item, level, len(jobs), matrix)
                if normalised and have[level] < wanted:
                    questions.append(normalised)
                    have[level] += 1
                    added += 1
            if not added:
                log.warning("Top-up for %s returned nothing usable; stopping", level)
                break

    # --- trim any level a batch overshot, newest first
    for level, wanted in validate.TARGET.items():
        indexed = [i for i, q in enumerate(questions) if q["level"] == level]
        for index in reversed(indexed[wanted:]):
            questions.pop(index)

    log.info("Generated %d question(s) before dedupe", len(questions))

    # --- duplicate removal, lexical then semantic
    semantic_pairs: list[dict] = []
    semantic_ran = False
    for round_no in range(1, MAX_REPAIR_ROUNDS + 1):
        doomed: dict[int, str] = {}

        for index in dedupe.duplicate_indices(questions):
            doomed[index] = "duplicates a question already in the set (concept key match)"

        for index, question in enumerate(questions):
            if index in doomed or question.get("reused"):
                continue
            clash = dedupe.clashes_with_bank(question["question"], bank)
            if clash:
                doomed[index] = f"duplicates a question from an earlier day: {clash!r}"

        if round_no == 1:
            try:
                payload, meta = engine_mod.ask_json(
                    prompts.semantic_dedupe_prompt(questions),
                    engine=engine, model=model, label="semantic duplicate pass")
                calls.append(meta)
                semantic_ran = True
                for pair in payload.get("duplicate_pairs") or []:
                    try:
                        drop = int(pair.get("drop"))
                    except (TypeError, ValueError):
                        continue
                    if 0 <= drop < len(questions):
                        semantic_pairs.append(pair)
                        doomed[drop] = ("semantic duplicate: "
                                        + str(pair.get("reason") or "same concept"))
            except engine_mod.EngineError as exc:
                # A failed dedupe pass is worth reporting, not worth losing the
                # run over - the concept-key pass has already run.
                log.warning("Semantic duplicate pass failed (%s)", str(exc)[:160])

        if not doomed:
            log.info("Round %d: no duplicates", round_no)
            break

        log.info("Round %d: replacing %d duplicate(s)", round_no, len(doomed))
        calls += _repair(questions, doomed, brief, jobs, matrix, engine, model)

    # --- validation, then one targeted repair pass on whatever it caught
    prep = _assemble(day, stamp, jobs, profile, matrix, bucketed, target_profile,
                     gap_analysis, priority, questions, analysis, calls,
                     engine, model, semantic_pairs, semantic_ran, results)
    result = validate.report(prep)

    # A replacement can itself come back missing a field, so this loops rather
    # than running once. Each round re-reads the gate, so it stops the moment
    # there is nothing left to fix instead of burning a fixed budget of calls.
    for round_no in range(1, MAX_REPAIR_ROUNDS + 1):
        reasons = _repair_reasons(result)
        if not reasons:
            break
        log.info("Validation round %d: regenerating %d question(s) - %s",
                 round_no, len(reasons), "; ".join(sorted(set(reasons.values()))))
        before = list(questions)
        calls += _repair(questions, reasons, brief, jobs, matrix, engine, model)
        if questions == before:
            log.warning("Repair produced no replacements; stopping the loop")
            break
        prep = _assemble(day, stamp, jobs, profile, matrix, bucketed, target_profile,
                         gap_analysis, priority, questions, analysis, calls,
                         engine, model, semantic_pairs, semantic_ran, results)
        result = validate.report(prep)

    prep["validation"] = result

    store.save_bank(store.remember(bank, prep["questions"], day))
    store.save_prep(prep)

    # Rebuild every day's page, not just today's: each one carries the date
    # picker listing all the others, so yesterday's page needs to learn that
    # today exists.
    from . import page as page_mod
    written = page_mod.rebuild_all()
    prep["page"] = str(next((p for p in written if stamp in p.name),
                            written[-1] if written else ""))
    return prep


def _repair_reasons(result: dict) -> dict[int, str]:
    """index -> the check that flagged it, for everything worth regenerating."""
    reasons: dict[int, str] = {}
    for check in result["checks"]:
        if check["ok"]:
            continue
        for index in check["indices"]:
            reasons[index] = check["check"]
    return {index: reason for index, reason in reasons.items()
            if index in validate.repairable(result)}


def repair_saved(day: str, engine: str | None = None, model: str | None = None) -> dict:
    """Re-validate a saved prep and regenerate only what fails. No re-scan.

    The whole point of §13's "regenerate only the problematic questions" is
    that a single bad field should not cost another twenty minutes and six
    dollars. This is that, standalone: it reuses the saved JDs, matrix and
    analysis, and only calls the model for the questions that failed.
    """
    prep = store.load_prep(day)
    if not prep or not prep.get("questions"):
        raise GenerationError(
            f"No saved preparation for {day}.\n"
            f"  Run:  python main.py --interview-prep --date {day}")

    engine = engine or engine_mod.default_engine()
    profile = profile_mod.load()
    brief = profile_mod.brief(profile)
    jobs = prep.get("jobs") or []
    matrix = prep.get("skill_matrix") or []
    questions = prep["questions"]
    calls = list(prep.get("calls") or [])

    result = validate.report(prep)
    for round_no in range(1, MAX_REPAIR_ROUNDS + 1):
        reasons = _repair_reasons(result)
        if not reasons:
            log.info("Nothing to repair for %s", day)
            break
        log.info("Round %d: regenerating %d question(s) - %s", round_no, len(reasons),
                 "; ".join(sorted(set(reasons.values()))))
        before = list(questions)
        calls += _repair(questions, reasons, brief, jobs, matrix, engine, model)
        if questions == before:
            log.warning("Repair produced no replacements; stopping the loop")
            break
        order = {"basic": 0, "intermediate": 1, "advanced": 2}
        questions.sort(key=lambda q: order.get(q["level"], 9))
        for number, question in enumerate(questions, start=1):
            question["id"] = f"Q{number}"
            question["number"] = number
        prep["questions"] = questions
        prep["coverage"] = _coverage(questions, matrix)
        result = validate.report(prep)

    prep["validation"] = result
    prep["calls"] = calls
    cost = sum(call.get("cost_usd") or 0 for call in calls)
    prep["cost_usd"] = round(cost, 4) if cost else None

    store.save_bank(store.remember(store.load_bank(), questions, day))
    store.save_prep(prep)

    from . import page as page_mod
    written = page_mod.rebuild_all()
    stamp = prep.get("run_id") or day
    prep["page"] = str(next((p for p in written if stamp in p.name),
                            written[-1] if written else ""))
    return prep


def _repair(questions: list[dict], doomed: dict[int, str], brief: str,
            jobs: list[dict], matrix: list[dict], engine: str | None,
            model: str | None) -> list[dict]:
    """Replace the flagged questions in place. Returns the call metadata."""
    calls: list[dict] = []
    by_level: dict[str, list[int]] = {}
    for index in sorted(doomed):
        by_level.setdefault(questions[index]["level"], []).append(index)

    for level, indices in by_level.items():
        keep = [q["question"] for i, q in enumerate(questions) if i not in doomed]
        reasons = [f"{questions[i]['question']!r} - {doomed[i]}" for i in indices]
        try:
            payload, meta = engine_mod.ask_json(
                prompts.repair_prompt(level, len(indices), brief, jobs, matrix,
                                      keep, reasons,
                                      focus=_under_covered(questions, matrix)),
                engine=engine, model=model, label=f"repair {level} x{len(indices)}")
        except engine_mod.EngineError as exc:
            log.warning("Repair call for %s failed (%s) - keeping the originals",
                        level, str(exc)[:160])
            continue
        calls.append(meta)

        replacements = [r for r in (_normalise(item, level, len(jobs), matrix)
                                    for item in payload.get("questions") or []) if r]
        for index, replacement in zip(indices, replacements):
            questions[index] = replacement
        if len(replacements) < len(indices):
            log.warning("Repair for %s returned %d of %d replacements - the "
                        "unreplaced ones stay and will be reported by validation",
                        level, len(replacements), len(indices))
    return calls


def _assemble(day, stamp, jobs, profile, matrix, bucketed, target_profile, gap_analysis,
              priority, questions, analysis, calls, engine, model,
              semantic_pairs, semantic_ran, results) -> dict:
    """Build the prep dict, ordering and numbering the questions."""
    order = {"basic": 0, "intermediate": 1, "advanced": 2}
    # Sort IN PLACE. prep["questions"] must be the same list object the caller
    # is holding, because validate.report() returns indices into prep and
    # _repair() overwrites by index in the caller's list. sorted() returns a
    # new list, and the two orders only coincide while `questions` happens to
    # be level-ordered already - which stops being true the moment the top-up
    # loop appends a basic question after the advanced batches, or the reuse
    # path prepends carried b/i/a questions ahead of the generated ones. Then
    # a flagged question survives and a healthy one at the same index is
    # destroyed, with the 30/40/30 counts intact so nothing notices.
    questions.sort(key=lambda q: order.get(q["level"], 9))
    ordered = questions
    for number, question in enumerate(ordered, start=1):
        question["id"] = f"Q{number}"
        question["number"] = number

    cost = sum(call.get("cost_usd") or 0 for call in calls)
    return {
        "date": day,
        "run_id": stamp,
        "run": store.split_run(stamp)[1],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": engine,
        "model": model,
        # A scheduled scan later the same day overwrites results-<date>.json,
        # so the file this was built from may no longer say what it said. The
        # ten job records are copied into this file wholesale, so the study
        # page stays correct either way - but the fingerprint below is what
        # lets you tell that the scan has moved on rather than wondering why
        # the page and the tracker disagree.
        "source": {
            "results_file": store.results_path(day).name,
            "results_mtime": _mtime(store.results_path(day)),
            "scan_generated": results.get("generated"),
            "worldwide": results.get("worldwide"),
            "posted_days": results.get("posted_days"),
            "new_only": results.get("new_only"),
            "naukri_total": len(results.get("naukri") or []),
            "linkedin_total": len(results.get("linkedin") or []),
            "top10_job_ids": [str(job.get("job_id")) for job in jobs],
        },
        "profile": {
            "name": profile["name"],
            "designation": profile["designation"],
            "total_years": profile["total_years"],
            "resume_path": profile["resume_path"],
        },
        "jobs": jobs,
        "target_profile": target_profile,
        "skill_matrix": matrix,
        "skill_buckets": {k: [row["skill"] for row in v] for k, v in bucketed.items()},
        "gap_analysis": gap_analysis,
        "priority_topics": priority,
        "study_order": [row["skill"] for row in skills.study_order(matrix, 20)],
        "questions": ordered,
        "coverage": _coverage(ordered, matrix),
        "semantic_duplicates": semantic_pairs,
        "semantic_pass_ran": semantic_ran,
        "calls": calls,
        "cost_usd": round(cost, 4) if cost else None,
    }


def _coverage(questions: list[dict], matrix: list[dict]) -> list[dict]:
    """The §12 mapping: question -> skill -> JDs -> level, as a flat table."""
    return [{
        "id": question["id"],
        "question": question["question"],
        "skill": question["skill"],
        "jds": question["jd_numbers"],
        "level": question["level"],
    } for question in questions]


def summarise(prep: dict) -> str:
    counts = prep.get("validation", {}).get("counts") or {}
    matrix = prep.get("skill_matrix") or []
    buckets = prep.get("skill_buckets") or {}
    lines = [
        "",
        f"  Interview preparation for {prep['date']}",
        f"  {len(prep.get('jobs') or [])} JDs analysed | "
        f"{len(prep.get('questions') or [])} questions "
        f"({counts.get('basic', 0)} basic / {counts.get('intermediate', 0)} intermediate "
        f"/ {counts.get('advanced', 0)} advanced)",
        f"  {len(matrix)} skills extracted | "
        f"{len(buckets.get('strong') or [])} strong, "
        f"{len(buckets.get('moderate') or [])} to strengthen, "
        f"{len(buckets.get('gap') or [])} gaps",
        "",
        f"  Target role: {(prep.get('target_profile') or {}).get('primary_role') or '-'}",
        "",
        "  Study first:",
    ]
    for row in matrix[:8]:
        lines.append(f"    {row['jd_count']:>2}/{row['jd_total']} JDs  "
                     f"{row['skill'][:34]:36} {row['profile_match']}")
    gaps = [row for row in matrix if row["status"] == "gap"][:6]
    if gaps:
        lines += ["", "  Biggest gaps:"]
        for row in gaps:
            lines.append(f"    {row['jd_count']:>2}/{row['jd_total']} JDs  {row['skill']}")
    if prep.get("cost_usd"):
        lines += ["", f"  Model cost: ${prep['cost_usd']:.2f} "
                      f"across {len(prep.get('calls') or [])} call(s)"]
    lines.append("")
    return "\n".join(lines)
