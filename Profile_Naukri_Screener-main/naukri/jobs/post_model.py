"""A fast, accurate "is this a software hiring post?" classifier, trained on your own posts.

    python -m naukri.jobs.post_model --build        gather every post the watchers kept into data/model/dataset.jsonl
    python -m naukri.jobs.post_model --label        the big local model (teacher) labels them, resumable: data/model/labels.jsonl
    python -m naukri.jobs.post_model --train        fit the small classifier on the labels, report cross-validated accuracy
    python -m naukri.jobs.post_model --eval         accuracy against YOUR labels (data/model/human.jsonl), when there are some
    python -m naukri.jobs.post_model --predict "text"

Why this shape: one narrow question ("is this a post by someone hiring for a software role?") is answered
best by a small model trained on examples of exactly that, not by a big general model. The big model
(Qwen 3.6 35B-A3B, TEACHER below) is accurate but takes 10-30 s a post on this laptop, so it only labels
the training set, once, overnight. The classifier it trains (fastembed text embeddings + logistic
regression, a few MB) answers in milliseconds, so the live feed and the watchers can use it on every post.

Labels, per post:  is_hiring, is_job_seeker, software_role, min_years (-1 = not stated);
relevant = is_hiring and not is_job_seeker and software_role - the one the classifier learns.

Honest limits: the classifier can only be as right as its labels. Cross-validation measures agreement with
the teacher; only labels you check yourself (human.jsonl) measure the truth, and no number here is 100%.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from . import linkedin_posts as lp

log = logging.getLogger("naukri.jobs.post_model")

ROOT = Path(__file__).resolve().parent.parent.parent
DIR = ROOT / "data" / "model"
DATASET = DIR / "dataset.jsonl"
LABELS = DIR / "labels.jsonl"
HUMAN = DIR / "human.jsonl"
MODEL_PATH = DIR / "post_clf.joblib"
LOG_PATH = ROOT / "logs" / "post_model.log"

TEACHER = "unsloth/Qwen3.6-35B-A3B-GGUF:Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

SYSTEM = "You label social media posts for a software engineer's job search. Reply with JSON only."
PROMPT = """POST (from {platform}):
{text}

AUTHOR HEADLINE: {headline}

Answer about this post:
- is_hiring: true only if the author, their company or their client is offering a job or internship now and invites candidates
  (apply, send a CV, DM, referral form). False for: a person looking for work, "I got hired / joined", layoffs or news,
  course or bootcamp ads, generic career advice, event invitations.
- is_job_seeker: true if the author is looking for a job, an internship or a referral for themselves.
- software_role: true if the role offered is software / IT engineering: software developer or engineer, SDE / SWE, backend,
  frontend, full stack, mobile, DevOps / cloud / SRE, data or ML engineer, QA / SDET. False for sales, HR, recruiter roles,
  mechanical / civil / electrical engineering, support or BPO. False when nothing is offered.
- min_years: the minimum years of experience asked; 0 for freshers or interns; -1 if not stated.
Return JSON: {{"is_hiring": bool, "is_job_seeker": bool, "software_role": bool, "min_years": int}}"""

SCHEMA = {"type": "object", "properties": {"is_hiring": {"type": "boolean"}, "is_job_seeker": {"type": "boolean"},
                                           "software_role": {"type": "boolean"}, "min_years": {"type": "integer"}},
          "required": ["is_hiring", "is_job_seeker", "software_role", "min_years"]}


# ----------------------------------------------------------------------------- data

def _read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def build_dataset() -> int:
    """Every distinct post the watchers kept, with the rules' verdict, into dataset.jsonl (merged, never shrinks)."""
    have = {r["id"]: r for r in _read_jsonl(DATASET)}
    seen_fp = {r.get("fp") for r in have.values()}
    added = 0
    for path, platform in ((ROOT / "data" / "posts" / "linkedin_posts.json", "linkedin"), (ROOT / "data" / "posts" / "social_posts.json", None)):
        try:
            posts = json.loads(path.read_text(encoding="utf-8")).get("posts") or []
        except (OSError, ValueError):
            continue
        for p in posts:
            text = (p.get("text") or "").strip()
            if len(text) < 30:
                continue
            pid = str(p.get("platform") or platform) + ":" + str(p.get("id"))
            fp = p.get("fp") or lp.fingerprint(p.get("author") or "", text)
            if pid in have or fp in seen_fp:
                continue
            info = lp.classify(text, p.get("headline") or "", open_to_work=bool(p.get("open_to_work")))
            have[pid] = {"id": pid, "fp": fp, "platform": p.get("platform") or platform, "text": text[:2500], "headline": (p.get("headline") or "")[:200],
                         "rules": {"hiring": info["hiring"], "seeker": info["seeker"], "software": bool(info["roles"]) and not info["off_field"],
                                   "min_years": (info.get("exp") or {}).get("min"), "relevant": lp.wanted(dict(info, fits_entry=True))}}
            seen_fp.add(fp)
            added += 1
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATASET.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in have.values()), encoding="utf-8")
    tmp.replace(DATASET)
    return added


# ----------------------------------------------------------------------------- the teacher

def _localai(model: str | None):
    scripts = ROOT.parent / "job-hunt" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    if model:
        os.environ["LOCAL_AI_MODEL"] = model            # read when the model is first loaded in this process
    os.environ.setdefault("LOCAL_AI_BUDGET_SECONDS", str(10 ** 7))   # labeling runs for hours, not one budget
    from jobbot import localai  # type: ignore
    return localai


def teacher_label(ai, rec: dict, timeout: float = 240) -> dict | None:
    out = ai.ask(PROMPT.format(platform=rec.get("platform") or "social media", text=rec["text"][:2200], headline=rec.get("headline") or "-"),
                 system=SYSTEM, max_tokens=80, json=True, schema=SCHEMA, temperature=0.0, timeout=timeout)
    if not isinstance(out, dict) or "is_hiring" not in out:
        return None
    lab = {k: bool(out.get(k)) for k in ("is_hiring", "is_job_seeker", "software_role")}
    y = out.get("min_years")
    lab["min_years"] = y if isinstance(y, int) and 0 <= y <= 30 else -1
    lab["relevant"] = lab["is_hiring"] and not lab["is_job_seeker"] and lab["software_role"]
    return lab


def label(limit: int | None = None, model: str = TEACHER) -> dict:
    """Label every dataset post the teacher has not labeled yet. Safe to stop and start again."""
    ai = _localai(model)
    if not ai.available("llm"):
        raise SystemExit("the local model is not available (llama-cpp-python missing?)")
    done = {r["id"] for r in _read_jsonl(LABELS) if r.get("model") == model}
    todo = [r for r in _read_jsonl(DATASET) if r["id"] not in done]
    if limit:
        todo = todo[:limit]
    log.info("teacher %s: %d to label (%d done before)", model.split(":")[-1], len(todo), len(done))
    n = failed = 0
    t0 = time.time()
    for rec in todo:
        t = time.time()
        lab = teacher_label(ai, rec)
        if lab is None:
            failed += 1
            log.warning("  %s: no answer (%.0fs)", rec["id"], time.time() - t)
            continue
        _append_jsonl(LABELS, {"id": rec["id"], "model": model, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **lab})
        n += 1
        if n % 10 == 0 or n <= 3:
            rate = (time.time() - t0) / n
            log.info("  %d/%d labeled, %.1fs a post, about %.0f min left", n, len(todo), rate, rate * (len(todo) - n) / 60)
    return {"labeled": n, "failed": failed, "seconds": round(time.time() - t0)}


# ----------------------------------------------------------------------------- the student

def _features(recs: list[dict]):
    import numpy as np
    from fastembed import TextEmbedding  # type: ignore
    emb = TextEmbedding(model_name=EMBED_MODEL)
    texts = [((r.get("headline") or "") + "\n" + r["text"])[:1800] for r in recs]
    X = np.array(list(emb.embed(texts, batch_size=32)), dtype="float32")
    rules = np.array([[float(bool((r.get("rules") or {}).get(k))) for k in ("hiring", "seeker", "software", "relevant")] for r in recs], dtype="float32")
    return np.hstack([X, rules])


def _training_set(model: str = TEACHER):
    """Dataset posts with a label: your own label wins over the teacher's."""
    data = {r["id"]: r for r in _read_jsonl(DATASET)}
    labels = {r["id"]: r for r in _read_jsonl(LABELS) if r.get("model") == model}
    labels.update({r["id"]: r for r in _read_jsonl(HUMAN)})
    ids = [i for i in labels if i in data]
    return [data[i] for i in ids], [bool(labels[i]["relevant"]) for i in ids], [i in {r["id"] for r in _read_jsonl(HUMAN)} for i in ids]


def train(model: str = TEACHER) -> dict:
    import joblib  # type: ignore
    import numpy as np
    from sklearn.linear_model import LogisticRegression  # type: ignore
    from sklearn.model_selection import StratifiedKFold, cross_val_predict  # type: ignore
    recs, y, _ = _training_set(model)
    if len(recs) < 60 or len(set(y)) < 2:
        raise SystemExit(f"only {len(recs)} labeled posts ({sum(y)} relevant) - label more first (--label)")
    X, y = _features(recs), np.array(y)
    clf = LogisticRegression(C=2.0, class_weight="balanced", max_iter=3000)
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
    pred = cross_val_predict(clf, X, y, cv=folds)
    rules = np.array([bool((r.get("rules") or {}).get("relevant")) for r in recs])
    rep = {"posts": len(y), "relevant": int(y.sum()),
           "classifier": _scores(y, pred), "rules_alone": _scores(y, rules)}
    clf.fit(X, y)
    DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"clf": clf, "embed": EMBED_MODEL, "teacher": model, "trained": time.strftime("%Y-%m-%d %H:%M"), "report": rep}, MODEL_PATH)
    return rep


def _scores(y, pred) -> dict:
    import numpy as np
    y, pred = np.asarray(y), np.asarray(pred)
    tp = int((y & pred).sum()); fp = int((~y & pred).sum()); fn = int((y & ~pred).sum())
    return {"accuracy": round(float((y == pred).mean()), 4), "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None, "false_keep": fp, "false_drop": fn}


_LOADED: dict = {}


def predict(text: str, headline: str = "") -> float | None:
    """Probability that this is a software hiring post, or None when no classifier has been trained."""
    if "m" not in _LOADED:
        try:
            import joblib  # type: ignore
            _LOADED["m"] = joblib.load(MODEL_PATH)
        except Exception:  # noqa: BLE001
            _LOADED["m"] = None
    m = _LOADED["m"]
    if m is None:
        return None
    info = lp.classify(text, headline)
    rec = {"text": text, "headline": headline, "rules": {"hiring": info["hiring"], "seeker": info["seeker"],
                                                         "software": bool(info["roles"]) and not info["off_field"],
                                                         "relevant": lp.wanted(dict(info, fits_entry=True))}}
    return float(m["clf"].predict_proba(_features([rec]))[0][1])


def evaluate() -> dict:
    """Accuracy against the labels you checked yourself (human.jsonl), for the teacher, the classifier and the rules."""
    import joblib  # type: ignore
    import numpy as np
    human = {r["id"]: r for r in _read_jsonl(HUMAN)}
    data = {r["id"]: r for r in _read_jsonl(DATASET)}
    teach = {r["id"]: r for r in _read_jsonl(LABELS)}
    ids = [i for i in human if i in data]
    if not ids:
        raise SystemExit("no labels of yours yet (data/model/human.jsonl)")
    y = np.array([bool(human[i]["relevant"]) for i in ids])
    out = {"posts": len(ids), "rules_alone": _scores(y, [bool(data[i]["rules"]["relevant"]) for i in ids])}
    if all(i in teach for i in ids):
        out["teacher"] = _scores(y, [bool(teach[i]["relevant"]) for i in ids])
    if MODEL_PATH.exists():
        m = joblib.load(MODEL_PATH)
        out["classifier"] = _scores(y, m["clf"].predict(_features([data[i] for i in ids])))
    return out


REVIEW_PATH = "data/model/review.json"       # on gh-pages, for the phone's labeling card


def review_set(n: int = 200, seed: int = 11) -> int:
    """A RANDOM sample of posts you have not labeled yet, published for the phone. Random on purpose: a test
    set picked by hand or by disagreement would make every score look better than it is."""
    import random
    human = {r["id"] for r in _read_jsonl(HUMAN)}
    pool = [r for r in _read_jsonl(DATASET) if r["id"] not in human]
    rnd = random.Random(seed)
    rnd.shuffle(pool)
    pick = [{"id": r["id"], "platform": r.get("platform"), "headline": r.get("headline") or "", "text": r["text"][:1800]} for r in pool[:n]]
    payload = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "count": len(pick), "labeled": len(human), "posts": pick}
    tools = ROOT.parent / "site" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import pages_git  # type: ignore
    repo_url = None
    try:
        from phone_publish import load_config  # type: ignore
        repo_url = (load_config() or {}).get("repo_url")
    except (SystemExit, Exception):  # noqa: BLE001
        repo_url = None
    pages_git.put_file(repo_url or pages_git.default_repo_url(), REVIEW_PATH, json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                       f"post labels: {len(pick)} posts to label")
    return len(pick)


def save_human(answers: dict) -> int:
    """The phone's answers ({post id: true = software hiring post}) into human.jsonl; a later answer wins."""
    data = {r["id"] for r in _read_jsonl(DATASET)}
    n = 0
    for pid, val in (answers or {}).items():
        if pid in data and isinstance(val, bool):
            _append_jsonl(HUMAN, {"id": pid, "relevant": val, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": "phone"})
            n += 1
    return n


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", handlers=handlers)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--label", action="store_true")
    mode.add_argument("--train", action="store_true")
    mode.add_argument("--eval", action="store_true")
    mode.add_argument("--predict", metavar="TEXT")
    mode.add_argument("--review-set", type=int, dest="review_set", metavar="N", help="publish N random posts for you to label on the phone")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default=TEACHER, help="the teacher GGUF as <hf repo>:<file>")
    args = ap.parse_args(argv)
    _setup_logging()
    if args.build:
        n = build_dataset()
        print(f"\n  {n} new post(s); dataset: {len(_read_jsonl(DATASET))} in {DATASET}\n")
    elif args.label:
        print(json.dumps(label(args.limit, args.model), indent=1))
    elif args.train:
        print(json.dumps(train(args.model), indent=1))
    elif args.eval:
        print(json.dumps(evaluate(), indent=1))
    elif args.review_set:
        print(f"\n  {review_set(args.review_set)} post(s) published for labeling on the phone (Posts tab)\n")
    else:
        print(predict(args.predict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
