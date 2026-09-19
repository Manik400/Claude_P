"""PC-side worker: the ONE auto-apply queue, carried out every 30 minutes.

    python phone_apply.py [--limit N] [--dry-run] [--once-report]
    (site\\phone_apply.bat; scheduled by site\\schedule_phone_apply.ps1)

Every job you want applied to - from a worldwide report, a Naukri scan, or
picked by the auto rule - lands in one queue, data/apply/queue.enc on the
gh-pages branch. This script is the only thing that writes it. Each run:

    1. refresh the gh-pages clone; publish any new Naukri scan pages from
       this PC (so the phone can queue their jobs too)
    2. read the phone's requests from data/apply/queue/*.enc and fold them
       into the queue: queue / remove / retry / pause / resume / settings /
       answers / profile / notes
    3. auto rule: when enabled, add every job scoring at least `min_score`
       from reports published since the last run
    4. apply to the next few queued jobs with the Naukri screener's own
       walkers (Naukri one-click / questionnaire, LinkedIn Easy Apply),
       same answers, same pacing, same daily caps, same ledger. Every
       other posting - Naukri "Apply on company site", LinkedIn's plain
       Apply, the worldwide boards' links - is opened and its Apply button
       followed to the company's form, which the career applier fills and
       submits; with Simplify Copilot set up (naukri/jobs/simplify.py, or
       the Simplify mode under Queue -> Rules) Simplify fills the form
       first. Only forms that want a login / account or show a CAPTCHA are
       left for you ("by hand")
    5. write data/apply/queue.enc: every item with its status, the progress
       (done / total / %), the questions waiting for you, when the PC last
       checked in - and data/apply/profile.enc for the Track tab
    6. push when something changed (or a heartbeat every couple of hours)

Nothing is lost when the PC is off: the requests wait on the branch and the
queue file keeps every item's state, so the first run after boot (the task
also fires at logon) picks up exactly where it stopped.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NAUKRI = os.path.join(ROOT, "Profile_Naukri_Screener-main")
JOBHUNT_SCRIPTS = os.path.join(ROOT, "job-hunt", "scripts")
sys.path.insert(0, HERE)
sys.path.insert(0, NAUKRI)
sys.path.insert(0, JOBHUNT_SCRIPTS)

import vault  # noqa: E402
from phone_publish import config_dir, load_config, save_config  # noqa: E402

LINKEDIN_VIEW = re.compile(r"linkedin\.com/jobs/view/(\d+)")
NAUKRI_ID = re.compile(r"naukri\.com/.*?-(\d{6,})(?:\?|$)")

# Ledger statuses that mean the item is finished. "offsite" is finished only
# when there is no Simplify browser to hand it to.
DONE = {"applied", "skipped", "questionnaire-declined", "submitted", "removed", "manual", "prefilled"}
WAITING = "questionnaire-pending"
RETRYABLE = {"error", "unconfirmed", "questionnaire-failed", "offsite-error"}
MAX_ATTEMPTS = 3
HEARTBEAT_HOURS = 1   # the phone calls the PC "off" after 1.25 h without a push

DEFAULT_SETTINGS = {
    "auto": {"enabled": False, "min_score": 60, "boards": ["linkedin", "naukri"]},
    "limit": 5,
    "offsite": "career",        # career | manual | simplify | simplify-submit
}
# "career": the PC opens the company's page, skips it when it wants a login or
# shows a CAPTCHA, otherwise fills the form from your details and submits
# (Profile_Naukri_Screener-main/naukri/jobs/career_apply.py).
# "simplify" / "simplify-submit": the same path, in the browser that has
# Simplify Copilot loaded - Simplify fills first, the career applier answers
# the rest and submits (naukri/jobs/simplify.py). Both submit: a headless
# browser cannot hold a half-filled form for you to finish later.
SIMPLIFY_MODES = ("simplify", "simplify-submit")


def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ files

def pages_dir(cfg: dict) -> str:
    target = os.path.join(config_dir(), "pages")
    env = dict(os.environ)
    if cfg.get("repo_url"):
        env["PAGES_REPO_URL"] = cfg["repo_url"]
    subprocess.run([sys.executable, os.path.join(HERE, "pages_git.py"), "checkout", target], check=True, env=env)
    return target


def read_enc(path: str, passphrase: str):
    with open(path, "rb") as f:
        return json.loads(vault.decrypt_bytes(f.read(), passphrase).decode("utf-8"))


def write_enc(path: str, data, passphrase: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(vault.encrypt_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), passphrase))


def load_index(pages: str) -> list[dict]:
    try:
        with open(os.path.join(pages, "data", "index.json"), encoding="utf-8") as f:
            return json.load(f).get("items") or []
    except (OSError, ValueError):
        return []


def report_jobs(pages: str, item: dict | None, passphrase: str) -> list[dict]:
    """The job list published next to a report, or []."""
    if not item:
        return []
    rel = (item.get("meta") or {}).get("jobs_file")
    if not rel:
        return []
    path = os.path.join(pages, rel)
    if not os.path.exists(path):
        return []
    try:
        data = read_enc(path, passphrase)
    except Exception as exc:
        log("cannot read job list %s: %s" % (rel, exc))
        return []
    return data if isinstance(data, list) else []


# ------------------------------------------------------------------ keys

def job_key(job: dict) -> tuple[str, str, str]:
    """(key, board, id) for a job dict from any report."""
    url = job.get("url") or ""
    extra = job.get("extra") or {}
    m = LINKEDIN_VIEW.search(url)
    if m:
        return "linkedin:" + m.group(1), "linkedin", m.group(1)
    nid = extra.get("naukri_id") or job.get("job_id")
    if not nid and "naukri.com" in url:
        m = NAUKRI_ID.search(url)
        nid = m.group(1) if m else None
    if nid and (job.get("source") == "naukri" or "naukri.com" in url):
        return "naukri:" + str(nid), "naukri", str(nid)
    digest = _djb2(url.split("#")[0].lower())
    return "web:" + digest, "web", digest


def _djb2(text: str) -> str:
    """The phone computes the same key (index.html sha1short): djb2, 32-bit, hex + 'x'."""
    h = 5381
    for ch in text:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return "%08x" % h + "x"


def item_from_job(job: dict, source: dict) -> dict:
    key, board, jid = job_key(job)
    extra = job.get("extra") or {}
    return {
        "key": key, "board": board, "job_id": jid, "url": job.get("url") or "",
        "title": job.get("title") or "", "company": job.get("company") or "",
        "location": job.get("location") or "", "score": job.get("score"),
        "source": source, "added_at": now_iso(), "status": "queued", "note": "", "at": "",
        "attempts": 0,
        "company_apply": bool(extra.get("company_apply")),
        "has_questionnaire": bool(extra.get("has_questionnaire")),
    }


# ------------------------------------------------------------------ queue

def load_queue(path: str, passphrase: str) -> dict:
    if os.path.exists(path):
        try:
            q = read_enc(path, passphrase)
            if isinstance(q, dict) and isinstance(q.get("items"), list):
                q.setdefault("settings", {})
                return q
        except Exception as exc:
            log("queue.enc unreadable (%s) - starting a fresh queue" % exc)
    return {"items": [], "paused": False, "settings": {}, "history": []}


def settings_of(queue: dict, cfg: dict) -> dict:
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    for src in (cfg.get("apply_settings") or {}, queue.get("settings") or {}):
        for k, v in src.items():
            if k == "auto" and isinstance(v, dict):
                s["auto"].update(v)
            else:
                s[k] = v
    return s


def apply_requests(queue: dict, requests_: list, pages: str, passphrase: str, dashboard, questions) -> dict:
    """Fold the phone's requests into the queue. Returns counts per type."""
    by_key = {i["key"]: i for i in queue["items"]}
    index = load_index(pages)
    counts: dict[str, int] = {}
    for name, path, req in requests_:
        kind = req.get("type")
        payload = req.get("payload") or {}
        counts[kind] = counts.get(kind, 0) + 1
        try:
            if kind in ("apply", "queue"):
                report_id = payload.get("report") or req.get("report")
                wanted = payload.get("jobs") if "jobs" in payload else req.get("jobs", "all")
                item = next((i for i in index if i.get("id") == report_id), None)
                jobs = report_jobs(pages, item, passphrase)
                chosen = None if wanted in ("all", None) else {str(j) for j in wanted}
                # Company-site postings the phone picked one by one travel in the payload
                # (their key is a hash of the URL, so the report copy is not needed).
                extra_items = [dict(j, _always=True) for j in (payload.get("items") or []) if isinstance(j, dict) and j.get("url")]
                added = 0
                for job in jobs + extra_items:
                    key, board, jid = job_key(job)
                    if job.get("fit") == "no":
                        continue
                    if chosen is not None and not job.get("_always") and key not in chosen and jid not in chosen:
                        continue
                    if key in by_key:
                        if by_key[key]["status"] in ("removed",):
                            by_key[key].update(status="queued", note="", attempts=0, added_at=now_iso())
                        continue
                    it = item_from_job(job, {"kind": (item or {}).get("kind") or payload.get("kind") or "jobhunt",
                                             "report": report_id, "title": (item or {}).get("title") or ""})
                    queue["items"].append(it)
                    by_key[key] = it
                    added += 1
                log("queue: +%d from %s" % (added, report_id))
            elif kind == "remove":
                for key in payload.get("keys") or []:
                    if key in by_key and by_key[key]["status"] not in ("applied", "submitted"):
                        by_key[key].update(status="removed", note="removed from the phone", at=now_iso())
            elif kind == "retry":
                for key in payload.get("keys") or []:
                    if key in by_key:
                        by_key[key].update(status="queued", note="", attempts=0, at=now_iso())
            elif kind == "pause":
                queue["paused"] = True
            elif kind == "resume":
                queue["paused"] = False
            elif kind == "settings":
                s = queue.setdefault("settings", {})
                for k, v in payload.items():
                    if k == "auto" and isinstance(v, dict):
                        s.setdefault("auto", {}).update(v)
                    elif k in ("limit", "offsite"):
                        s[k] = v
            elif kind == "answers":
                pending = questions.load_pending()
                given = {questions.key(k): v for k, v in (req.get("answers") or payload).items()}
                n = 0
                for entry in pending:
                    answer = given.get(questions.key(entry.get("question", "")))
                    if answer and str(answer).strip():
                        entry["answer"] = str(answer).strip()
                        n += 1
                questions.save_pending(pending)
                log("answers: %d written to questions.yaml" % n)
            elif kind == "profile":
                dashboard.save_answers(payload)
            elif kind == "notes":
                for job_id, note in payload.items():
                    if isinstance(note, dict):
                        dashboard.save_note({"job_id": job_id, "status": note.get("status", ""),
                                             "note": note.get("note", "")})
            else:
                log("unknown request %s in %s" % (kind, name))
        except Exception as exc:
            log("request %s failed: %s" % (name, exc))
    return counts


def auto_enqueue(queue: dict, cfg: dict, pages: str, passphrase: str, settings: dict) -> int:
    """The auto rule: queue every job scoring >= min_score from reports not seen before."""
    auto = settings.get("auto") or {}
    if not auto.get("enabled"):
        return 0
    seen = set(cfg.setdefault("auto_seen_reports", []))
    by_key = {i["key"] for i in queue["items"]}
    boards = set(auto.get("boards") or ["linkedin", "naukri"])
    min_score = float(auto.get("min_score") or 0)
    added = 0
    for item in load_index(pages):
        if item.get("kind") not in ("jobhunt", "naukri") or item["id"] in seen:
            continue
        if not (item.get("meta") or {}).get("jobs_file"):
            continue
        for job in report_jobs(pages, item, passphrase):
            key, board, jid = job_key(job)
            if board not in boards or key in by_key or job.get("fit") == "no":
                continue
            if (job.get("score") or 0) < min_score:
                continue
            it = item_from_job(job, {"kind": item["kind"], "report": item["id"], "title": item.get("title", ""),
                                     "auto": True})
            queue["items"].append(it)
            by_key.add(key)
            added += 1
        seen.add(item["id"])
    cfg["auto_seen_reports"] = sorted(seen)[-200:]
    if added:
        log("auto: +%d job(s) scoring %s+" % (added, int(min_score)))
    return added


def sync_from_ledger(queue: dict, ledger) -> None:
    """Every item's status comes from the screener's ledger, the record of truth."""
    for it in queue["items"]:
        if it["status"] in ("removed",) or it["board"] == "web":
            continue
        # Ledger keys: "linkedin:<id>" for LinkedIn, the bare Naukri jobId for Naukri.
        entry = ledger.entries.get(it["key"] if it["board"] == "linkedin" else it["job_id"])
        if not entry:
            continue
        st = entry.get("status")
        if st and st != it["status"]:
            it["status"] = st
            it["note"] = entry.get("note", "")
            it["at"] = entry.get("at", "")


def progress_of(queue: dict) -> dict:
    live = [i for i in queue["items"] if i["status"] != "removed"]
    n = len(live)

    def count(*sts):
        return sum(1 for i in live if i["status"] in sts)

    applied = count("applied", "submitted")
    waiting = count(WAITING)
    manual = count("offsite", "manual", "prefilled")
    skipped = count("skipped", "questionnaire-declined")
    failed = count("error", "unconfirmed", "questionnaire-failed", "offsite-error", "failed")
    queued = count("queued", "retry")
    done = applied + manual + skipped + failed + waiting
    return {"total": n, "applied": applied, "waiting": waiting, "manual": manual, "skipped": skipped,
            "failed": failed, "queued": queued, "done": done,
            "pct": int(round(100.0 * done / n)) if n else 0}


# ------------------------------------------------------------------ apply

def run_applies(queue: dict, settings: dict, limit: int, dry_run: bool, autoapply, config_mod, NaukriJob) -> dict:
    mode = settings.get("offsite", "career")
    simplify_on = mode in SIMPLIFY_MODES
    if simplify_on:
        mode = "career"
    # Company-site postings left "by hand" before the career applier existed
    # get one go at it.
    career_again = [i for i in queue["items"] if mode == "career" and not i.get("career_tried")
                    and i["status"] in ("manual", "offsite")]
    todo = [i for i in queue["items"] if i["status"] in ("queued", "retry") or
            (i["status"] in RETRYABLE and i.get("attempts", 0) < MAX_ATTEMPTS)] + career_again
    if queue.get("paused"):
        log("apply: queue paused from the phone (%d waiting)" % len(todo))
        return {}
    if not todo:
        return {}
    todo.sort(key=lambda i: -(i.get("score") or 0))
    naukri_jobs, cards = [], []
    for it in todo:
        if it["board"] == "naukri":
            naukri_jobs.append(NaukriJob(job_id=it["job_id"], title=it["title"], company=it["company"],
                                         url=it["url"], location=it.get("location"),
                                         company_apply=bool(it.get("company_apply")),
                                         has_questionnaire=bool(it.get("has_questionnaire")), source="phone"))
            naukri_jobs[-1].score = it.get("score") or 100
        elif it["board"] == "linkedin":
            cards.append({"job_id": it["job_id"], "url": it["url"], "title": it["title"],
                          "company": it["company"], "location": it.get("location", ""), "easy_apply": True})
    for it in todo:
        it["attempts"] = it.get("attempts", 0) + 1
    profile = config_mod.load_profile()
    config = dict(config_mod.load(profile=profile))
    config["scan_apply_min_score"] = 0        # queued by you: no score gate
    config["career_apply"] = mode == "career" and config.get("career_apply", True)
    if simplify_on:
        config["simplify"] = True
    web = [i for i in todo if i["board"] == "web"]
    web_jobs = [{"job_id": i["key"], "url": i["url"], "title": i["title"], "company": i["company"],
                 "score": i.get("score"), "retry": i.get("attempts", 0) > 1 or i["status"] in ("queued", "retry")}
                for i in web] if mode == "career" else []
    log("apply: %d Naukri + %d LinkedIn + %d company-site queued, at most %d each this run%s"
        % (len(naukri_jobs), len(cards), len(web_jobs), limit, " (dry run)" if dry_run else ""))
    outcomes = {}
    if naukri_jobs or cards or web_jobs:
        outcomes = autoapply.run(naukri_jobs, cards, config, profile, headless=True, dry_run=dry_run,
                                 per_run=limit, include_backlog=False, project="phone", web_jobs=web_jobs)
    # Company-site postings: the career applier's outcomes, or Simplify / by hand.
    if mode == "career":
        import naukri.jobs.career_apply as career_mod
        for it in todo:
            hit = outcomes.get(it["key"] if it["board"] != "naukri" else "naukri:" + it["job_id"])
            if not hit:
                continue
            it["career_tried"] = it.get("career_tried") or hit["status"] in career_mod.STATUSES or it["board"] != "web"
            if it["board"] == "web":
                it.update(status=career_mod.queue_status(hit["status"]), note=hit["note"], at=now_iso())
    elif web:
        for it in web:
            it.update(status="manual", note="company site - open it from the report and apply by hand",
                      at=now_iso())
    return outcomes


# ------------------------------------------------------------------ main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="applications per board per run (default: phone setting, else 5)")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run", help="report what would be sent; push nothing")
    ap.add_argument("--no-publish", action="store_true", dest="no_publish", help="skip publishing new Naukri scan pages")
    args = ap.parse_args(argv)

    cfg = load_config()
    passphrase = cfg.get("passphrase") or vault.get_passphrase()
    if not passphrase:
        raise SystemExit("phone_apply: no passphrase - run site\\setup_phone.bat")
    pages = pages_dir(cfg)
    apply_dir = os.path.join(pages, "data", "apply")
    queue_dir = os.path.join(apply_dir, "queue")
    done_dir = os.path.join(apply_dir, "done")
    queue_path = os.path.join(apply_dir, "queue.enc")
    os.makedirs(queue_dir, exist_ok=True)

    # 1. New Naukri scan pages from this PC reach the phone without a separate schedule.
    if not args.no_publish and not args.dry_run:
        try:
            subprocess.run([sys.executable, os.path.join(HERE, "phone_publish.py"), "naukri", "--no-push"], check=False)
        except Exception as exc:
            log("publish naukri: %s" % exc)
        cfg = load_config()   # the publisher records what it published

    from naukri.jobs import autoapply, config as config_mod, dashboard, questions
    from naukri.jobs.ledger import Ledger
    from naukri.jobs.model import Job as NaukriJob

    queue = load_queue(queue_path, passphrase)
    before = json.dumps(queue, sort_keys=True)
    # Once: company-site postings switch from "by hand" to the career applier
    # (the old default was written into the queue's settings on every run).
    if not cfg.get("career_default_set"):
        if (queue.get("settings") or {}).get("offsite") in (None, "manual"):
            queue.setdefault("settings", {})["offsite"] = "career"
        cfg["career_default_set"] = True

    # 2. The phone's requests.
    requests_ = []
    for name in sorted(os.listdir(queue_dir)):
        if name.endswith(".enc"):
            path = os.path.join(queue_dir, name)
            try:
                requests_.append((name, path, read_enc(path, passphrase)))
            except Exception as exc:
                log("skipping unreadable request %s: %s" % (name, exc))
    counts = apply_requests(queue, requests_, pages, passphrase, dashboard, questions)
    if counts:
        log("requests: " + ", ".join("%s=%d" % kv for kv in sorted(counts.items())))
    settings = settings_of(queue, cfg)
    limit = args.limit or int(os.environ.get("NAUKRI_APPLY_LIMIT") or settings.get("limit") or 5)

    # 3. Auto rule.
    auto_enqueue(queue, cfg, pages, passphrase, settings)

    # 4. Apply.
    outcomes = run_applies(queue, settings, limit, args.dry_run, autoapply, config_mod, NaukriJob)
    ledger = Ledger()
    sync_from_ledger(queue, ledger)
    for it in queue["items"]:
        if it["status"] in RETRYABLE and it.get("attempts", 0) >= MAX_ATTEMPTS:
            it["status"] = "failed"
            it["note"] = (it.get("note") or "") + " (gave up after %d tries; tap retry to try again)" % MAX_ATTEMPTS

    if not args.dry_run:
        os.makedirs(done_dir, exist_ok=True)
        for name, path, _req in requests_:
            if os.path.exists(path):
                os.replace(path, os.path.join(done_dir, name))
        # keep done/ small
        old = sorted(os.listdir(done_dir))[:-50]
        for name in old:
            try:
                os.remove(os.path.join(done_dir, name))
            except OSError:
                pass

    # 5. The queue file the phone reads.
    today = date.today().isoformat()
    applied_today = {
        "linkedin": sum(1 for k, e in ledger.entries.items() if k.startswith("linkedin:") and e.get("status") == "applied" and str(e.get("at", "")).startswith(today)),
        "naukri": sum(1 for k, e in ledger.entries.items() if not k.startswith("linkedin:") and e.get("status") == "applied" and str(e.get("at", "")).startswith(today)),
    }
    caps, simplify_default = {}, False
    try:
        c = config_mod.load()
        caps = {"linkedin": c.get("linkedin_max_applies_per_day"), "naukri": c.get("max_auto_applies")}
        simplify_default = bool(c.get("simplify"))
    except Exception:
        pass
    # Finished items older than 30 days drop off; the applications log keeps the record.
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    queue["items"] = [i for i in queue["items"] if not (i["status"] in DONE and (i.get("at") or i.get("added_at") or "") < cutoff)]
    queue["items"] = [i for i in queue["items"] if i["status"] != "removed" or (i.get("at") or "") > (datetime.now() - timedelta(days=2)).isoformat()]
    queue.update({
        "updated": now_iso(),
        "pc": {"last_seen": now_iso(), "host": os.environ.get("COMPUTERNAME", ""), "limit": limit,
               "applied_today": applied_today, "caps": caps, "dry_run": args.dry_run,
               "offsite": settings.get("offsite", "career"),
               "simplify_ready": os.path.exists(os.path.join(config_dir(), "simplify-profile")),
               "simplify_default": simplify_default},
        "settings": settings,
        "progress": progress_of(queue),
        "pending_questions": [
            {"question": e.get("question"), "options": e.get("options") or [], "board": e.get("board"),
             "jobs": [{"title": j.get("title"), "company": j.get("company")} for j in (e.get("jobs") or [])[:5]]}
            for e in questions.load_pending() if not str(e.get("answer") or "").strip()
        ],
    })
    queue["history"] = (queue.get("history") or [])[-30:]
    if outcomes and outcomes.get("_summary"):
        s = outcomes["_summary"]
        queue["history"].append({"at": now_iso(), "naukri": s.get("naukri"), "linkedin": s.get("linkedin"),
                                 "dry_run": args.dry_run})
    write_enc(queue_path, queue, passphrase)
    if not args.dry_run:
        save_config(cfg)

    # 6. Track tab data.
    profile_path = os.path.join(apply_dir, "profile.enc")
    try:
        state = dashboard.state()
        state.pop("generated", None)
        track = {
            "answers": state["answers"], "bank": state["bank"], "pending": state["pending"],
            "applications": state["applications"], "counts": state["counts"],
            "manual_statuses": state["manual_statuses"], "kind_labels": state["kind_labels"],
            "gmail": {"configured": state["gmail"]["configured"], "synced_at": state["gmail"]["synced_at"]},
        }
        fp = json.dumps(track, sort_keys=True, ensure_ascii=False)
        old = None
        if os.path.exists(profile_path):
            try:
                old = json.dumps(read_enc(profile_path, passphrase), sort_keys=True, ensure_ascii=False)
            except Exception:
                old = None
        if fp != old:
            write_enc(profile_path, track, passphrase)
            log("track: profile.enc refreshed (%d application(s))" % len(track["applications"]))
    except Exception as exc:
        log("track: could not build profile.enc: %s" % exc)

    if outcomes and outcomes.get("_summary"):
        log(autoapply.summarise(outcomes).strip())
    p = queue["progress"]
    log("queue: %d item(s), %d%% done - %d applied, %d queued, %d waiting on you, %d manual, %d failed"
        % (p["total"], p["pct"], p["applied"], p["queued"], p["waiting"], p["manual"], p["failed"]))
    if args.dry_run:
        log("dry run: queue written locally, nothing pushed")
        return 0

    after = json.dumps({k: v for k, v in queue.items() if k not in ("updated", "pc")}, sort_keys=True)
    before_cmp = json.dumps({k: v for k, v in json.loads(before).items() if k not in ("updated", "pc", "progress", "pending_questions", "settings")}, sort_keys=True)
    after_cmp = json.dumps({k: v for k, v in json.loads(after).items() if k not in ("progress", "pending_questions", "settings")}, sort_keys=True)
    last_push = cfg.get("last_heartbeat_push") or ""
    stale = last_push < (datetime.now() - timedelta(hours=HEARTBEAT_HOURS)).isoformat()
    changed = subprocess.run(["git", "status", "--porcelain", "--", "data"], cwd=pages,
                             capture_output=True, text=True).stdout.strip() != ""
    if before_cmp == after_cmp and not requests_ and not stale and not changed:
        log("nothing changed; not pushing")
        return 0
    subprocess.run([sys.executable, os.path.join(HERE, "pages_git.py"), "push", pages,
                    "queue: %d%% of %d done, %d applied today" % (p["pct"], p["total"], sum(applied_today.values()))],
                   check=True)
    cfg["last_heartbeat_push"] = now_iso()
    save_config(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
