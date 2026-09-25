"""Daily accuracy tracking and the self-learning loop.

Two jobs, both rebuilt from what the bots already record, so they can be re-run
at any time and never drift from the logs:

ACCURACY (`build_accuracy`) - one row per day in data/metrics/accuracy.json,
accuracy.csv and accuracy.html (published to the phone site):

    search      jobs found and listed per scan kind (Last 24h / Early / All
                jobs), how many the model rates relevant (score >= review line
                55) and strong (>= 72), and - once you act on listings - how
                many you kept vs removed ("your precision")
    apply       every attempt from applications.jsonl split into success /
                failed / pending (waiting on your answer) / manual (company
                site, no button) / skipped, per board and per strategy
                (one-click, questionnaire, company site, LinkedIn Easy Apply)
    answers     screening answers by source (your saved answer, the answer
                bank, the local model) and how often those forms went through
    outcomes    replies from Gmail (responses.json) and the statuses you set on
                the dashboard / phone Track tab: viewed, shortlisted,
                interview, offer, rejected
    prep        interview-prep runs: questions, validation, cost
    learning    what the model learned that day (below) and how many labels
                it had to learn from

SELF-LEARNING (`learn`) - data/metrics/learned.json, read by score.py:

    Every job with a signal gets a label: an interview / shortlist / offer is
    strong positive, a job you queued yourself on the phone is positive, a
    successful apply is weakly positive, a job you removed is negative, a
    rejection is mildly negative. The label is spread over the job's features
    (company, search keyword, skills, title words), and each feature's weight
    is its smoothed average label. score.py adds the mean weight of a job's
    features as a "learned" component (clamped to +/-8 points, so it nudges
    the ranking and never overrides the profile match).

    With the local embedding model installed it also keeps two "taste"
    centroids - the average embedding of the jobs you liked and of those you
    removed - and adds up to +/-3 for how much closer a new job sits to the
    first than the second.

    Apply strategies are learned the same way: success rate per board and
    method, so the report shows which routes work and autoapply can try the
    likelier ones first (`strategy_rank`).

Nothing learns from fewer than MIN_LABELS labelled jobs - until then the
learned component is 0 and the page says so.
"""
from __future__ import annotations

import csv
import html
import json
import logging
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("naukri.learning")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JOBS = DATA / "jobs"
INTERVIEW = DATA / "interview"
METRICS = DATA / "metrics"
LEARNED = METRICS / "learned.json"
ACCURACY_JSON = METRICS / "accuracy.json"
ACCURACY_CSV = METRICS / "accuracy.csv"
ACCURACY_HTML = METRICS / "accuracy.html"
SCANS_LOG = METRICS / "scans.jsonl"

MIN_LABELS = 5
SMOOTHING = 3.0         # a feature seen once moves its weight a quarter of the way
LEARNED_CAP = 8.0       # points, either way
TASTE_CAP = 3.0
REVIEW_LINE, STRONG_LINE = 55, 72

LABELS = {
    "offer": 4.0, "interview": 3.0, "shortlisted": 2.5, "viewed": 1.0,
    "queued-by-you": 1.5, "applied": 0.3,
    "rejected": -1.0, "removed": -2.0, "withdrawn": -0.5,
}
APPLY_BUCKET = {
    "applied": "success",
    "error": "failed", "questionnaire-failed": "failed", "unconfirmed": "failed",
    "questionnaire": "pending", "questionnaire-pending": "pending", "queued": "pending",
    "offsite": "manual", "no-button": "manual",
    "already": "skipped", "skipped": "skipped", "questionnaire-declined": "skipped",
}
STOP = {"and", "the", "for", "with", "senior", "junior", "lead", "developer", "engineer", "software",
        "sr", "jr", "ii", "iii", "iv", "of", "in", "to", "a", "an", "we", "are", "hiring", "remote"}


# ---------------------------------------------------------------- reading

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _attempts() -> list[dict]:
    path = JOBS / "applications.jsonl"
    rows = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return [r for r in rows if not r.get("dry_run")]


def _job_index() -> dict[str, dict]:
    """"<board>:<id>" -> {title, company, skills, keyword, text} from every saved scan."""
    index: dict[str, dict] = {}
    for path in sorted(JOBS.glob("results-*.json")):
        data = _read_json(path, {})
        for j in data.get("naukri") or []:
            src = str(j.get("source") or "")
            index[f"naukri:{j.get('job_id')}"] = {
                "title": j.get("title") or "", "company": j.get("company") or "",
                "skills": j.get("skills") or [],
                "keyword": src.split(":", 1)[1] if src.startswith("search:") else src,
                "text": f"{j.get('title')}. Skills: {', '.join(j.get('skills') or [])}. {(j.get('description') or '')[:1500]}",
            }
        for c in data.get("linkedin") or []:
            index.setdefault(f"linkedin:{c.get('job_id')}", {
                "title": c.get("title") or "", "company": c.get("company") or "", "skills": [],
                "keyword": "", "text": f"{c.get('title')}. {' '.join(c.get('metadata') or [])}",
            })
    return index


def _key(board: str | None, job_id) -> str:
    job_id = str(job_id or "")
    if ":" in job_id:
        return job_id
    return f"{(board or 'naukri').lower()}:{job_id}"


def _phone_queue() -> list[dict]:
    import os
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    q = _read_json(Path(base) / "JobHuntPhone" / "pages" / "data" / "apply" / "queue.json", {})
    return q.get("items") or []


def _outcomes() -> dict[str, str]:
    """"<board>:<id>" -> strongest outcome kind from Gmail and your own statuses."""
    out: dict[str, str] = {}
    try:
        from .jobs import responses
        for job_id, slot in responses.per_application().items():
            if slot.get("kind") in LABELS:
                out[_key("naukri", job_id)] = slot["kind"]
    except Exception as exc:  # Gmail not set up is the normal case
        log.debug("responses unavailable: %s", exc)
    notes = _read_json(JOBS / "application_notes.json", {})
    for job_id, note in notes.items():
        status = (note or {}).get("status")
        if status in LABELS:
            out[_key("naukri", job_id)] = status
    return out


# ---------------------------------------------------------------- features

def features(title: str, company: str = "", skills=None, keyword: str = "") -> list[str]:
    feats = []
    if company:
        feats.append("company:" + company.strip().lower())
    if keyword:
        feats.append("keyword:" + keyword.strip().lower())
    for s in skills or []:
        s = str(s).strip().lower()
        if s:
            feats.append("skill:" + s)
    for w in re.findall(r"[a-z][a-z0-9+#.]{1,}", (title or "").lower()):
        if w not in STOP and len(w) > 1:
            feats.append("title:" + w)
    return sorted(set(feats))


def _job_features(job) -> list[str]:
    src = str(getattr(job, "source", "") or "")
    return features(getattr(job, "title", "") or "", getattr(job, "company", "") or "",
                    getattr(job, "skills", None) or [],
                    src.split(":", 1)[1] if src.startswith("search:") else "")


# ---------------------------------------------------------------- learning

def _labels(attempts, index, queue, outcomes) -> dict[str, tuple[float, str]]:
    labels: dict[str, tuple[float, str]] = {}

    def put(key, kind):
        value = LABELS[kind]
        old = labels.get(key)
        # the strongest evidence wins: an interview outranks "applied"
        if old is None or abs(value) > abs(old[0]):
            labels[key] = (value, kind)

    for r in attempts:
        if r.get("status") == "applied":
            put(_key(r.get("board"), r.get("job_id")), "applied")
    for item in queue:
        key = item.get("key") or _key(item.get("board"), item.get("job_id"))
        if item.get("status") == "removed":
            put(key, "removed")
        elif not (item.get("source") or {}).get("auto", True):
            put(key, "queued-by-you")
    for key, kind in outcomes.items():
        put(key, kind)
    return labels


def learn(save: bool = True) -> dict:
    """Recompute data/metrics/learned.json from every signal on disk."""
    attempts = _attempts()
    index = _job_index()
    for r in attempts:  # jobs never in a saved scan still carry title/company
        index.setdefault(_key(r.get("board"), r.get("job_id")),
                         {"title": r.get("title") or "", "company": r.get("company") or "",
                          "skills": [], "keyword": "", "text": r.get("title") or ""})
    labels = _labels(attempts, index, _phone_queue(), _outcomes())

    sums, counts = defaultdict(float), Counter()
    for key, (value, _kind) in labels.items():
        info = index.get(key)
        if not info:
            continue
        for f in features(info["title"], info["company"], info["skills"], info["keyword"]):
            sums[f] += value
            counts[f] += 1
    weights = {f: round(sums[f] / (counts[f] + SMOOTHING), 4) for f in sums if counts[f] >= 2}

    taste = {}
    liked = [index[k]["text"] for k, (v, _) in labels.items() if v >= 1.0 and k in index]
    disliked = [index[k]["text"] for k, (v, _) in labels.items() if v < 0 and k in index]
    try:
        from naukri import localai
        if localai.available("embed") and len(liked) >= MIN_LABELS:
            taste["liked"] = _centroid(localai.embed(liked[-200:]))
            if len(disliked) >= 3:
                taste["disliked"] = _centroid(localai.embed(disliked[-200:]))
    except Exception as exc:
        log.debug("taste centroid skipped: %s", exc)

    kinds = Counter(kind for _v, kind in labels.values())
    model = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "labels": len(labels),
        "label_kinds": dict(kinds),
        "active": len(labels) >= MIN_LABELS and bool(weights),
        "weights": weights,
        "taste": taste,
        "strategies": strategy_stats(attempts),
    }
    if save:
        METRICS.mkdir(parents=True, exist_ok=True)
        LEARNED.write_text(json.dumps(model, indent=1), encoding="utf-8")
        _MODEL_CACHE.clear()
    log.info("learning: %d labelled job(s) %s, %d feature weight(s)%s",
             len(labels), dict(kinds), len(weights), ", taste centroid" if taste else "")
    return model


def _centroid(vectors):
    if not vectors:
        return None
    dim = len(vectors[0])
    c = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    return [round(x, 5) for x in c]


_MODEL_CACHE: dict = {}


def model() -> dict:
    """learned.json, cached per file version."""
    try:
        stamp = LEARNED.stat().st_mtime
    except OSError:
        return {}
    if _MODEL_CACHE.get("stamp") != stamp:
        _MODEL_CACHE.clear()
        _MODEL_CACHE.update(stamp=stamp, data=_read_json(LEARNED, {}))
    return _MODEL_CACHE["data"]


def adjustment(job) -> float:
    """The "learned" score component for a job, in points (0 until enough labels)."""
    m = model()
    if not m.get("active"):
        return 0.0
    weights = m.get("weights") or {}
    hits = [weights[f] for f in _job_features(job) if f in weights]
    points = 0.0
    if hits:
        # mean weight, scaled so a feature set that always led to an interview (+3)
        # is worth the full cap; more matching evidence counts a little more
        points = (sum(hits) / len(hits)) * (LEARNED_CAP / 3.0) * min(1.0, 0.5 + len(hits) / 8)
    points += getattr(job, "taste", 0.0) or 0.0
    return round(max(-LEARNED_CAP, min(LEARNED_CAP, points)), 1)


def prepare_taste(jobs, texts) -> None:
    """Set job.taste (+/-TASTE_CAP) from the liked / disliked centroids, batched."""
    m = model()
    taste = m.get("taste") or {}
    if not m.get("active") or not taste.get("liked"):
        return
    try:
        from naukri import localai
        vectors = localai.embed(texts)
    except Exception:
        vectors = None
    if not vectors:
        return
    for job, v in zip(jobs, vectors):
        close = localai.cosine(v, taste["liked"])
        far = localai.cosine(v, taste["disliked"]) if taste.get("disliked") else close - 0.05
        # cosines from bge-small sit in a narrow band; 0.1 apart is a clear lean
        job.taste = round(max(-TASTE_CAP, min(TASTE_CAP, (close - far) * 30)), 2)


# ---------------------------------------------------------------- strategies

def strategy_of(row: dict) -> str:
    board = (row.get("board") or "naukri").lower()
    status, note = row.get("status") or "", (row.get("note") or "").lower()
    if board == "linkedin":
        return "linkedin easy apply"
    if status in ("offsite", "no-button") or "company site" in note or "career" in note or "simplify" in note:
        return f"{board} company site"
    if row.get("answers") or status.startswith("questionnaire"):
        return f"{board} questionnaire"
    return f"{board} one-click"


def strategy_stats(attempts) -> dict:
    stats: dict[str, Counter] = defaultdict(Counter)
    for r in attempts:
        bucket = APPLY_BUCKET.get(r.get("status") or "", "other")
        stats[strategy_of(r)][bucket] += 1
    out = {}
    for name, c in stats.items():
        tried = c["success"] + c["failed"]
        out[name] = dict(c, tried=tried,
                         success_rate=round(c["success"] / tried, 3) if tried else None)
    return out


MIN_STRATEGY_TRIES = 10


def _chance(stats: dict) -> float | None:
    """Laplace-smoothed chance an attempt ends "applied". Manual (left for you)
    and pending (waiting on an answer) count as not-applied here: for choosing
    what to try next, a route that never finishes is as bad as one that fails."""
    n = sum(stats.get(k, 0) for k in ("success", "failed", "manual", "pending"))
    if n < MIN_STRATEGY_TRIES:
        return None
    return (stats.get("success", 0) + 1) / (n + 2)


def _mean_chance(strategies: dict) -> float:
    known = [c for c in (_chance(s) for s in strategies.values()) if c is not None]
    return sum(known) / len(known) if known else 0.5


def strategy_rank(row: dict) -> float:
    """Learned chance an attempt of this kind succeeds (the average when unknown)."""
    strategies = model().get("strategies") or {}
    c = _chance(strategies.get(strategy_of(row)) or {})
    return _mean_chance(strategies) if c is None else c


def job_priority(job, board: str = "naukri") -> float:
    """Multiplier (0.75..1.25) on a job's score when choosing what to apply to
    first: above 1 for routes that work better than average, below for worse."""
    status = "offsite" if getattr(job, "company_apply", False) else ""
    answers = [1] if getattr(job, "has_questionnaire", False) else []
    strategies = model().get("strategies") or {}
    lean = strategy_rank({"board": board, "status": status, "answers": answers}) - _mean_chance(strategies)
    return 1.0 + max(-0.25, min(0.25, lean))


# ---------------------------------------------------------------- scans log

def log_scan(results: dict, kept, cards, outcomes: dict | None) -> None:
    """One line per scan in data/metrics/scans.jsonl (called by export.run)."""
    scores = [float(getattr(j, "score", 0) or 0) for j in kept]
    kind = ("early" if results.get("early") else
            "last-24h" if results.get("posted_days") == 1 else
            "all" if not results.get("posted_days") and not results.get("new_only") else "custom")
    summary = (outcomes or {}).get("_summary") or {}
    buckets = Counter(APPLY_BUCKET.get((v or {}).get("status", ""), "other")
                      for k, v in (outcomes or {}).items() if not k.startswith("_"))
    learned = [getattr(j, "score_breakdown", {}).get("learned", 0) for j in kept]
    row = {
        "at": datetime.now().isoformat(timespec="seconds"), "date": date.today().isoformat(),
        "kind": kind, "naukri": len(kept), "linkedin": len(cards or []),
        "relevant": sum(s >= REVIEW_LINE for s in scores), "strong": sum(s >= STRONG_LINE for s in scores),
        "mean_score": round(sum(scores) / len(scores), 1) if scores else None,
        "learned_moved": sum(1 for x in learned if x), "apply": dict(buckets),
        "apply_summary": {k: v for k, v in summary.items() if isinstance(v, (int, float, str))},
    }
    METRICS.mkdir(parents=True, exist_ok=True)
    with SCANS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _scans() -> list[dict]:
    rows = []
    try:
        for line in SCANS_LOG.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return rows


# ---------------------------------------------------------------- accuracy

def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def day_metrics(day: str, attempts, scans, queue, outcomes, learned) -> dict:
    todays = [r for r in attempts if str(r.get("at", "")).startswith(day)]
    buckets = Counter(APPLY_BUCKET.get(r.get("status") or "", "other") for r in todays)
    boards = defaultdict(Counter)
    for r in todays:
        boards[(r.get("board") or "naukri").lower()][APPLY_BUCKET.get(r.get("status") or "", "other")] += 1
    tried = buckets["success"] + buckets["failed"]

    answers = defaultdict(Counter)
    for r in todays:
        for a in r.get("answers") or []:
            src = str(a.get("source") or "unknown").split(" (")[0]
            src = "local model" if src.startswith("local-ai") else src
            answers[src]["used"] += 1
            answers[src]["form_went_through" if r.get("status") == "applied" else "form_did_not"] += 1

    day_scans = [s for s in scans if s.get("date") == day]
    if not day_scans:
        # Days before scans.jsonl existed: the day's last results file stands in.
        saved = _read_json(JOBS / f"results-{day}.json", None)
        if saved:
            scores = [float(j.get("score") or 0) for j in saved.get("naukri") or []]
            day_scans = [{"kind": ("early" if saved.get("early") else "last-24h" if saved.get("posted_days") == 1
                                   else "all" if not saved.get("posted_days") and not saved.get("new_only") else "custom"),
                          "naukri": len(scores), "linkedin": len(saved.get("linkedin") or []),
                          "relevant": sum(s >= REVIEW_LINE for s in scores),
                          "strong": sum(s >= STRONG_LINE for s in scores)}]
    by_kind = {}
    for s in day_scans:
        k = by_kind.setdefault(s["kind"], Counter())
        for f in ("naukri", "linkedin", "relevant", "strong", "learned_moved"):
            k[f] += s.get(f) or 0
        k["scans"] += 1
    listed = sum(s.get("naukri") or 0 for s in day_scans)
    relevant = sum(s.get("relevant") or 0 for s in day_scans)

    day_queue = [i for i in queue if str(i.get("added_at") or i.get("at") or "").startswith(day)]
    removed = sum(1 for i in day_queue if i.get("status") == "removed")
    kept_by_you = sum(1 for i in day_queue if i.get("status") != "removed"
                      and not (i.get("source") or {}).get("auto", True))

    preps = []
    for path in sorted(INTERVIEW.glob(f"prep-{day}-r*.json")):
        p = _read_json(path, {})
        v = p.get("validation") or {}
        preps.append({"run": p.get("run_id") or path.stem, "questions": len(p.get("questions") or []),
                      "valid": v.get("ok"), "failed_checks": [c.get("check") for c in v.get("checks") or [] if not c.get("ok")],
                      "cost_usd": p.get("cost_usd"), "engine": p.get("engine"), "model": p.get("model")})

    todays_keys = {_key(r.get("board"), r.get("job_id")) for r in todays}
    replies = Counter(outcomes[k] for k in todays_keys if k in outcomes)

    return {
        "date": day,
        "search": {
            "scans": len(day_scans), "listed": listed, "relevant": relevant,
            "relevant_pct": _pct(relevant, listed),
            "strong": sum(s.get("strong") or 0 for s in day_scans),
            "by_kind": {k: dict(v, relevant_pct=_pct(v["relevant"], v["naukri"])) for k, v in by_kind.items()},
            "your_precision_pct": _pct(kept_by_you, kept_by_you + removed) if (kept_by_you + removed) else None,
            "removed_by_you": removed,
        },
        "apply": dict(buckets, attempts=len(todays), success_rate_pct=_pct(buckets["success"], tried),
                      by_board={b: dict(c) for b, c in boards.items()}),
        "answers": {k: dict(v, went_through_pct=_pct(v["form_went_through"], v["used"])) for k, v in answers.items()},
        "outcomes": dict(replies),
        "prep": preps,
        "learning": {"labels": learned.get("labels", 0), "active": learned.get("active", False),
                     "features": len(learned.get("weights") or {})},
    }


def build_accuracy(days: int = 30) -> Path:
    """Rewrite accuracy.json / .csv / .html for the last `days` days (learns first)."""
    learned = learn()
    attempts, scans, queue, outcomes = _attempts(), _scans(), _phone_queue(), _outcomes()
    active_days = sorted({str(r.get("at", ""))[:10] for r in attempts} | {s.get("date") for s in scans}
                         | {p.name[5:15] for p in INTERVIEW.glob("prep-*.json")})
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    active_days = [d for d in active_days if d and d >= cutoff]
    rows = {d: day_metrics(d, attempts, scans, queue, outcomes, learned) for d in active_days}

    METRICS.mkdir(parents=True, exist_ok=True)
    ACCURACY_JSON.write_text(json.dumps({"updated": datetime.now().isoformat(timespec="seconds"),
                                         "days": rows, "learned": _learned_summary(learned)}, indent=1),
                             encoding="utf-8")
    with ACCURACY_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "scans", "listed", "relevant_pct", "strong", "your_precision_pct",
                    "attempts", "success", "failed", "pending", "manual", "skipped", "success_rate_pct",
                    "replies", "interviews", "prep_runs", "prep_valid", "learned_labels"])
        for d, m in sorted(rows.items()):
            s, a, o = m["search"], m["apply"], m["outcomes"]
            w.writerow([d, s["scans"], s["listed"], s["relevant_pct"], s["strong"], s["your_precision_pct"],
                        a["attempts"], a.get("success", 0), a.get("failed", 0), a.get("pending", 0),
                        a.get("manual", 0), a.get("skipped", 0), a["success_rate_pct"],
                        sum(o.values()), o.get("interview", 0) + o.get("shortlisted", 0) + o.get("offer", 0),
                        len(m["prep"]), sum(1 for p in m["prep"] if p["valid"]), m["learning"]["labels"]])
    ACCURACY_HTML.write_text(_page(rows, learned), encoding="utf-8")
    log.info("accuracy: %d day(s) written to %s", len(rows), ACCURACY_HTML)
    return ACCURACY_HTML


def _learned_summary(learned: dict, n: int = 12) -> dict:
    w = learned.get("weights") or {}
    ranked = sorted(w.items(), key=lambda kv: kv[1])
    return {"labels": learned.get("labels", 0), "label_kinds": learned.get("label_kinds", {}),
            "active": learned.get("active", False), "taste": sorted((learned.get("taste") or {}).keys()),
            "top_positive": ranked[::-1][:n], "top_negative": [kv for kv in ranked[:n] if kv[1] < 0],
            "strategies": learned.get("strategies", {})}


# ---------------------------------------------------------------- page

def _page(rows: dict, learned: dict) -> str:
    from .accordion import SNIPPET
    e = html.escape
    fmt = lambda v, suf="": "–" if v is None else f"{v:g}{suf}" if isinstance(v, (int, float)) else e(str(v))

    trs = []
    for d, m in sorted(rows.items(), reverse=True):
        s, a, o = m["search"], m["apply"], m["outcomes"]
        kinds = ", ".join(f"{k} {v.get('naukri', 0)}/{fmt(v.get('relevant_pct'), '%')}" for k, v in sorted(s["by_kind"].items()))
        prep = "; ".join(f"{p['questions']}q {'ok' if p['valid'] else 'issues'}" + (f" ${p['cost_usd']:.2f}" if p.get("cost_usd") else "")
                         for p in m["prep"]) or "–"
        trs.append(
            f"<tr><td>{e(d)}</td><td>{s['scans']}</td><td>{s['listed']}</td><td>{fmt(s['relevant_pct'], '%')}</td>"
            f"<td>{s['strong']}</td><td>{fmt(s['your_precision_pct'], '%')}</td><td class='k'>{e(kinds) or '–'}</td>"
            f"<td>{a['attempts']}</td><td class='ok'>{a.get('success', 0)}</td><td class='bad'>{a.get('failed', 0)}</td>"
            f"<td class='warn'>{a.get('pending', 0)}</td><td>{a.get('manual', 0)}</td><td>{fmt(a['success_rate_pct'], '%')}</td>"
            f"<td>{e(', '.join(f'{k} {v}' for k, v in o.items())) or '–'}</td><td class='k'>{e(prep)}</td></tr>")

    strat = learned.get("strategies") or {}
    srows = "".join(
        f"<tr><td>{e(n)}</td><td>{s.get('tried', 0)}</td><td class='ok'>{s.get('success', 0)}</td>"
        f"<td class='bad'>{s.get('failed', 0)}</td><td class='warn'>{s.get('pending', 0)}</td>"
        f"<td>{s.get('manual', 0)}</td><td>{fmt(None if s.get('success_rate') is None else round(100 * s['success_rate'], 1), '%')}</td></tr>"
        for n, s in sorted(strat.items(), key=lambda kv: -(kv[1].get("tried") or 0)))

    summ = _learned_summary(learned)
    pos = "".join(f"<li><code>{e(f)}</code> <b class='ok'>+{w:.2f}</b></li>" for f, w in summ["top_positive"] if w > 0) or "<li>none yet</li>"
    neg = "".join(f"<li><code>{e(f)}</code> <b class='bad'>{w:.2f}</b></li>" for f, w in summ["top_negative"]) or "<li>none yet</li>"
    status = ("<b class='ok'>active</b> - adjusting scores by up to ±%g points" % LEARNED_CAP if summ["active"]
              else f"<b class='warn'>collecting</b> - needs {MIN_LABELS}+ labelled jobs before it changes any score")
    kinds = ", ".join(f"{k} {v}" for k, v in summ["label_kinds"].items()) or "none"

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Accuracy - Learning</title>
<style>
  html {{ font-size: clamp(14.5px, calc(0.28vw + 11.2px), 18px); }} @media (max-width: 899px) {{ html {{ font-size: 16px; }} }}  /* text scales with the screen */

  :root {{ --bg:#f6f5f2; --card:#fff; --ink:#1c1917; --muted:#6b6560; --line:#e4e0da; --ok:#15803d; --bad:#b91c1c; --warn:#b45309; }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#131211; --card:#1d1b19; --ink:#f2efea; --muted:#a39d95; --line:#322f2b; --ok:#4ade80; --bad:#f87171; --warn:#fbbf24; }} }}
  :root[data-theme="dark"] {{ --bg:#131211; --card:#1d1b19; --ink:#f2efea; --muted:#a39d95; --line:#322f2b; --ok:#4ade80; --bad:#f87171; --warn:#fbbf24; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:0.875rem/1.5 -apple-system,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:none; margin:0; padding:16px clamp(14px, 2.2vw, 36px); }}
  h1 {{ font-size: 1.375rem; margin:4px 0 2px; }} .sub {{ color:var(--muted); margin:0 0 14px; }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:12px; margin:0 0 14px; }}
  section > details.fgrp {{ display:block; border:0; padding:0; }}
  section > details.fgrp > summary {{ display:flex; padding:12px 14px; font-size: 0.875rem; font-weight:600; letter-spacing:0;
    text-transform:none; opacity:1; }}
  .body {{ padding:0 14px 14px; overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size: 0.8125rem; }}
  th, td {{ text-align:left; padding:6px 8px; border-top:1px solid var(--line); white-space:nowrap; }}
  th {{ color:var(--muted); font-weight:600; font-size: 0.75rem; }}
  td.k {{ white-space:normal; min-width:180px; color:var(--muted); }}
  .ok {{ color:var(--ok); }} .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }}
  ul {{ margin:6px 0; padding-left:18px; }} code {{ font-size: 0.75rem; }}
  .cols {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:10px 24px; }}
  .note {{ color:var(--muted); font-size: 0.8125rem; }}
</style></head><body><main>
<h1>Accuracy &amp; learning</h1>
<p class="sub">Rebuilt after every scan · updated {e(datetime.now().strftime('%Y-%m-%d %H:%M'))} · learning is {status}</p>

<section><details class="fgrp" data-acc="accuracy.daily" open><summary>Day by day</summary><div class="body">
<table><thead><tr><th>Date</th><th>Scans</th><th>Listed</th><th>Relevant</th><th>Strong</th><th>Your precision</th>
<th>By scan (listed / relevant)</th><th>Attempts</th><th>Success</th><th>Failed</th><th>Pending</th><th>Manual</th><th>Apply rate</th>
<th>Replies</th><th>Interview prep</th></tr></thead><tbody>{''.join(trs) or '<tr><td colspan=15>No data yet.</td></tr>'}</tbody></table>
<p class="note"><b>Relevant</b> = listed jobs the model scores {REVIEW_LINE}+; <b>strong</b> = {STRONG_LINE}+. <b>Your precision</b> = of the jobs
you acted on in the phone queue, the share you kept rather than removed. <b>Apply rate</b> = success / (success + failed); pending =
waiting on your answer, manual = company site or no apply button.</p>
</div></details></section>

<section><details class="fgrp" data-acc="accuracy.strategy" open><summary>Apply strategies (all time)</summary><div class="body">
<table><thead><tr><th>Strategy</th><th>Tried</th><th>Success</th><th>Failed</th><th>Pending</th><th>Manual</th><th>Success rate</th></tr></thead>
<tbody>{srows or '<tr><td colspan=7>No attempts yet.</td></tr>'}</tbody></table>
<p class="note">The apply step reads these rates and tries the routes that work first.</p>
</div></details></section>

<section><details class="fgrp" data-acc="accuracy.learned" open><summary>What the model has learned</summary><div class="body">
<p class="note">{summ['labels']} labelled job(s): {e(kinds)}.{' Taste centroid from the local embedding model: ' + ', '.join(summ['taste']) + '.' if summ['taste'] else ''}
Labels come from interviews / shortlists / offers (Gmail replies or the status you set), jobs you queue or remove on the phone, and successful applies.</p>
<div class="cols"><div><b>Pushes a job up</b><ul>{pos}</ul></div><div><b>Pushes a job down</b><ul>{neg}</ul></div></div>
</div></details></section>
</main>{SNIPPET}</body></html>"""
