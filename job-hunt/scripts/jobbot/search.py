"""Orchestrator: run every applicable (source, country) pair concurrently, then dedup / filter / annotate."""
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import REMOTE
from .experience import annotate
from .http import Blocked
from .textutil import ROLE_SYNONYMS, GENERIC_ROLE_WORDS, strip_accents


def _weak_match(ctx, text):
    """True if the job text matches any requested role.

    A role with specific words ("python" in "python developer") needs one of them somewhere in the text,
    so generic "Software Engineer" results that platforms add do not flood the report.
    A generic-only role ("software engineer") matches on the generic words and their translations."""
    t = strip_accents(text or "").lower()
    for strong, weak in ctx._role_terms:
        if strong:
            if any(ctx._has(s, t) for s in strong):
                return True
            continue
        for w in weak:
            for syn in set(ROLE_SYNONYMS.get(w, [w]) + [w]):
                if syn in t:
                    return True
    return False


def run_search(ctx, sources, log=print, workers=6):
    """Returns (jobs, statuses) where statuses is a list of dicts per (source, country)."""
    tasks = []
    for src in sources:
        for cc in ctx.countries:
            if src.applies_to(cc):
                tasks.append((src, cc))
    log(f"search: {len(tasks)} source/country tasks with {workers} workers")
    statuses, jobs = [], []

    def work(src, cc):
        t0 = time.time()
        try:
            found = src.search(ctx, cc) or []
            return dict(source=src.key, source_name=src.name, country=cc, status="ok", count=len(found),
                        seconds=round(time.time() - t0, 1)), found
        except Blocked as e:
            return dict(source=src.key, source_name=src.name, country=cc, status="blocked", count=0,
                        seconds=round(time.time() - t0, 1), error=str(e)[:160]), []
        except Exception as e:  # noqa: BLE001 - a broken source must not kill the run
            return dict(source=src.key, source_name=src.name, country=cc, status="error", count=0,
                        seconds=round(time.time() - t0, 1), error=f"{type(e).__name__}: {str(e)[:160]}",
                        trace=traceback.format_exc()[-800:]), []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, src, cc): (src, cc) for src, cc in tasks}
        for fut in as_completed(futs):
            st, found = fut.result()
            statuses.append(st)
            jobs.extend(found)
            flag = {"ok": "ok", "blocked": "BLOCKED", "error": "ERROR"}[st["status"]]
            log(f"  {st['source_name']:<28} {st['country']:<7} {flag:<8} {st['count']:>4} jobs  {st['seconds']}s"
                + (f"  ({st.get('error')})" if st.get("error") else ""))
    jobs = dedup(jobs)
    jobs = postfilter(ctx, jobs, log)
    for j in jobs:
        annotate(j, ctx.user_years)
        j.relevance = ctx.relevance(j.title, " ".join(j.skills) + " " + j.snippet + " " + j.description[:800])
    return jobs, statuses


def dedup(jobs):
    by_url, by_key = {}, {}
    out = []
    for j in jobs:
        u = j.dedup_url()
        k = j.dedup_key()
        prev = by_url.get(u) or by_key.get(k)
        if prev is None:
            by_url[u] = j
            by_key[k] = j
            out.append(j)
            continue
        # keep the richer record, remember the other platform
        keep, drop = (prev, j) if len(prev.description) >= len(j.description) else (j, prev)
        if drop.source_name not in keep.also_on and drop.source_name != keep.source_name:
            keep.also_on.append(drop.source_name)
        if not keep.posted and drop.posted:
            keep.posted = drop.posted
        if not keep.salary and drop.salary:
            keep.salary = drop.salary
        for s in drop.skills:
            if s not in keep.skills:
                keep.skills.append(s)
        if keep is j:
            out[out.index(prev)] = j
            for a in prev.also_on:
                if a not in j.also_on and a != j.source_name:
                    j.also_on.append(a)
            by_url[u] = j
            by_key[k] = j
    return out


def postfilter(ctx, jobs, log=print):
    kept, dropped_excl, dropped_rel, dropped_old = [], 0, 0, 0
    for j in jobs:
        if ctx.excluded(j.title):
            dropped_excl += 1
            continue
        if not ctx.fresh(j.posted):
            dropped_old += 1
            continue
        if not ctx.loose and not _weak_match(ctx, j.text_blob()):
            dropped_rel += 1
            continue
        kept.append(j)
    log(f"filter: kept {len(kept)}, dropped {dropped_rel} unrelated, {dropped_excl} excluded by term, {dropped_old} too old")
    return kept


def apply_fit_filter(jobs, mode="default"):
    """mode: default (drop clear mismatches), strict (only fits), all (keep everything)."""
    if mode == "all":
        return jobs
    if mode == "strict":
        return [j for j in jobs if j.fit in ("fit",)]
    return [j for j in jobs if j.fit != "no"]


def sort_jobs(jobs):
    fit_rank = {"fit": 0, "unknown": 1, "stretch": 2, "over": 3, "no": 4}
    return sorted(jobs, key=lambda j: (
        -(j.score if j.score is not None else -1),
        fit_rank.get(j.fit, 5),
        -j.relevance,
        j.posted or "0000-00-00",
    ), reverse=False) if any(j.score is not None for j in jobs) else sorted(
        jobs, key=lambda j: (fit_rank.get(j.fit, 5), -j.relevance, "" if j.posted is None else "", j.posted or ""), reverse=False)


def country_order(codes):
    return [c for c in codes if c != REMOTE] + ([REMOTE] if REMOTE in codes else [])
