"""PC-side poller: carry out the auto-apply requests made from the phone.

    python phone_apply.py [--limit N] [--dry-run]        (site\\phone_apply.bat; scheduled by
                                                          site\\schedule_phone_apply.ps1)

The phone cannot apply by itself and GitHub's runners must not (no LinkedIn
login there, and a datacenter IP on your account is how it gets restricted).
So the phone leaves a request on the gh-pages branch and this script, on your
PC with the real session, does the work:

    1. refresh the gh-pages clone; read data/apply/queue/*.enc
    2. "answers" requests -> the answers go into the Naukri screener's
       data/jobs/questions.yaml, exactly as if typed in its dashboard
    3. "apply" requests -> the report's LinkedIn postings (data/jobhunt/<id>.jobs.enc)
       become cards for the Naukri screener's applier: same Easy Apply
       walker, same answers, same pacing, same daily LinkedIn cap, same
       applications log (tagged "phone")
    4. write data/apply/status.enc: every requested posting's outcome, the
       requests' progress, and the screening questions waiting for you
    5. write data/apply/profile.enc: what the PC dashboard shows - your
       answers form, the answer bank, and every application with its
       questions, answers, Gmail replies and your notes - so the phone's
       Track tab can show it (after the passphrase) and edit it. "profile"
       and "notes" requests from that tab are saved exactly as the
       dashboard would save them.
    6. move finished requests to data/apply/done/, push (only when
       something changed)

A request whose postings are not all settled yet stays in the queue and the
next poll continues it - a request for 60 postings is applied in batches of
`--limit` (default 5) every poll, never all at once.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NAUKRI = os.path.join(ROOT, "Profile_Naukri_Screener-main")
JOBHUNT_SCRIPTS = os.path.join(ROOT, "job-hunt", "scripts")
sys.path.insert(0, HERE)
sys.path.insert(0, NAUKRI)
sys.path.insert(0, JOBHUNT_SCRIPTS)

import vault  # noqa: E402
from phone_publish import config_dir, load_config  # noqa: E402

LINKEDIN_VIEW = re.compile(r"linkedin\.com/jobs/view/(\d+)")
SETTLED = {"applied", "skipped", "offsite", "questionnaire-declined"}


def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


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


def report_jobs(pages: str, report_id: str, passphrase: str) -> list[dict]:
    """The job list published next to a report, or []."""
    index_path = os.path.join(pages, "data", "index.json")
    try:
        with open(index_path, encoding="utf-8") as f:
            items = json.load(f).get("items") or []
    except (OSError, ValueError):
        items = []
    item = next((i for i in items if i.get("id") == report_id), None)
    rel = (item or {}).get("meta", {}).get("jobs_file") or ("data/jobhunt/%s.jobs.enc" % report_id)
    path = os.path.join(pages, rel)
    if not os.path.exists(path):
        log("no job list for report %s (%s) - was it made before auto-apply existed?" % (report_id, rel))
        return []
    data = read_enc(path, passphrase)
    return data if isinstance(data, list) else []


def linkedin_id(url: str) -> str | None:
    m = LINKEDIN_VIEW.search(url or "")
    return m.group(1) if m else None


def cards_for(request: dict, jobs: list[dict]) -> list[dict]:
    wanted = request.get("jobs")
    chosen = None if wanted == "all" else {str(j) for j in (wanted or [])}
    cards = []
    for job in jobs:
        job_id = linkedin_id(job.get("url", ""))
        if not job_id or job.get("fit") == "no":
            continue
        if chosen is not None and job_id not in chosen:
            continue
        cards.append({
            "job_id": job_id,
            "url": "https://www.linkedin.com/jobs/view/%s/" % job_id,
            "title": job.get("title") or "",
            "company": job.get("company") or "",
            "location": job.get("location") or "",
            "easy_apply": True,
            "_score": job.get("score") or 0,
        })
    cards.sort(key=lambda c: -(c["_score"] or 0))
    return cards


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None,
                    help="applications per poll (default: NAUKRI_APPLY_LIMIT, else 5)")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run", help="report what would be sent")
    args = ap.parse_args(argv)
    limit = args.limit
    if limit is None:
        raw = os.environ.get("NAUKRI_APPLY_LIMIT", "").strip()
        limit = int(raw) if raw.isdigit() else 5

    cfg = load_config()
    passphrase = cfg.get("passphrase") or vault.get_passphrase()
    if not passphrase:
        raise SystemExit("phone_apply: no passphrase - run site\\setup_phone.bat")
    pages = pages_dir(cfg)
    queue_dir = os.path.join(pages, "data", "apply", "queue")
    done_dir = os.path.join(pages, "data", "apply", "done")
    status_path = os.path.join(pages, "data", "apply", "status.enc")
    os.makedirs(queue_dir, exist_ok=True)

    from naukri.jobs import applications, autoapply, config as config_mod, questions
    from naukri.jobs.ledger import Ledger

    requests_ = []
    for name in sorted(os.listdir(queue_dir)):
        if not name.endswith(".enc"):
            continue
        path = os.path.join(queue_dir, name)
        try:
            requests_.append((name, path, read_enc(path, passphrase)))
        except Exception as exc:
            log("skipping unreadable request %s: %s" % (name, exc))

    # 1. Answers first, so the apply pass can use them straight away.
    answered = 0
    finished: list[str] = []
    for name, path, req in requests_:
        if req.get("type") != "answers":
            continue
        pending = questions.load_pending()
        given = {questions.key(k): v for k, v in (req.get("answers") or {}).items()}
        for entry in pending:
            answer = given.get(questions.key(entry.get("question", "")))
            if answer and str(answer).strip():
                entry["answer"] = str(answer).strip()
                answered += 1
        questions.save_pending(pending)
        finished.append(name)
    if answered:
        log("%d answer(s) from the phone written to questions.yaml" % answered)

    # Edits made in the phone's Track tab: the answers form and application notes.
    from naukri.jobs import dashboard
    edits = 0
    for name, path, req in requests_:
        if req.get("type") == "profile":
            dashboard.save_answers(req.get("payload") or {})
            edits += 1
            finished.append(name)
        elif req.get("type") == "notes":
            for job_id, note in (req.get("payload") or {}).items():
                if isinstance(note, dict):
                    dashboard.save_note({"job_id": job_id, "status": note.get("status", ""),
                                         "note": note.get("note", "")})
            edits += 1
            finished.append(name)
    if edits:
        log("%d edit(s) from the phone saved" % edits)

    # 2. Apply requests: gather every wanted posting across requests.
    ledger = Ledger()
    cards: dict[str, dict] = {}
    per_request: dict[str, list[str]] = {}
    for name, path, req in requests_:
        if req.get("type") != "apply":
            continue
        jobs = report_jobs(pages, req.get("report", ""), passphrase)
        wanted = cards_for(req, jobs)
        per_request[name] = ["linkedin:" + c["job_id"] for c in wanted]
        for card in wanted:
            cards.setdefault(card["job_id"], card)
        if not wanted:
            finished.append(name)  # nothing applicable; nothing to wait for

    outcomes: dict = {}
    todo = [c for c in cards.values() if ledger.status("linkedin:" + c["job_id"]) not in SETTLED
            and ledger.status("linkedin:" + c["job_id"]) != autoapply.WAITING]
    pending_answers = bool(answered)
    if todo or pending_answers:
        profile = config_mod.load_profile()
        config = config_mod.load(profile=profile)
        log("apply: %d posting(s) still to do across %d request(s), at most %d this poll%s"
            % (len(todo), len(per_request), limit, " (dry run)" if args.dry_run else ""))
        outcomes = autoapply.run([], todo, config, profile, headless=True, dry_run=args.dry_run,
                                 per_run=limit, include_backlog=False, project="phone")
        ledger = Ledger()
    else:
        log("apply: nothing to do (%d request(s) in the queue)" % len(per_request))

    # 3. Progress per request; finished ones move to done/.
    today = date.today().isoformat()
    queue_status = []
    for name, path, req in requests_:
        if req.get("type") != "apply":
            continue
        ids = per_request.get(name, [])
        states = {i: ledger.status(i) for i in ids}
        settled = sum(1 for s in states.values() if s in SETTLED or s == autoapply.WAITING)
        done = not ids or settled == len(ids)
        if done and name not in finished:
            finished.append(name)
        queue_status.append({
            "file": name, "report": req.get("report"), "requested_at": req.get("requested_at"),
            "jobs": len(ids), "applied": sum(1 for s in states.values() if s == "applied"),
            "waiting": sum(1 for s in states.values() if s == autoapply.WAITING),
            "settled": settled, "done": done, "note": req.get("note", ""),
        })
    if not args.dry_run:
        os.makedirs(done_dir, exist_ok=True)
        for name in finished:
            src = os.path.join(queue_dir, name)
            if os.path.exists(src):
                os.replace(src, os.path.join(done_dir, name))

    # 4. Status for the phone: every posting ever requested, from the ledger.
    previous = {}
    if os.path.exists(status_path):
        try:
            previous = read_enc(status_path, passphrase)
        except Exception:
            previous = {}
    jobs_status = dict(previous.get("jobs") or {})
    for job_id, card in cards.items():
        key = "linkedin:" + job_id
        entry = ledger.entries.get(key) or {}
        jobs_status[job_id] = {
            "status": entry.get("status") or ("queued" if not args.dry_run else "would-apply"),
            "note": entry.get("note", ""), "at": entry.get("at", ""),
            "title": card["title"], "company": card["company"], "url": card["url"],
        }
    for key, entry in ledger.entries.items():
        if key.startswith("linkedin:") and key[9:] in jobs_status:
            jobs_status[key[9:]].update({"status": entry.get("status"), "note": entry.get("note", ""),
                                         "at": entry.get("at", "")})
    applied_today = sum(1 for k, e in ledger.entries.items()
                        if k.startswith("linkedin:") and e.get("status") == "applied"
                        and str(e.get("at", "")).startswith(today))
    config_cap = None
    try:
        config_cap = config_mod.load()["linkedin_max_applies_per_day"]
    except Exception:
        pass
    status = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "jobs": jobs_status,
        "queue": queue_status + [q for q in (previous.get("queue") or []) if q.get("done")][-20:],
        "pending_questions": [
            {"question": e.get("question"), "options": e.get("options") or [], "board": e.get("board"),
             "jobs": [{"title": j.get("title"), "company": j.get("company")} for j in (e.get("jobs") or [])[:5]]}
            for e in questions.load_pending() if not str(e.get("answer") or "").strip()
        ],
        "counts": {"applied_today": applied_today, "cap": config_cap, "limit": limit,
                   "answers_received": answered},
        "dry_run": args.dry_run,
    }
    write_enc(status_path, status, passphrase)

    # 5. The dashboard's data for the phone's Track tab.
    profile_path = os.path.join(pages, "data", "apply", "profile.enc")
    try:
        state = dashboard.state()
        state.pop("generated", None)
        track = {
            "answers": state["answers"], "bank": state["bank"], "pending": state["pending"],
            "applications": state["applications"], "counts": state["counts"],
            "manual_statuses": state["manual_statuses"], "kind_labels": state["kind_labels"],
            "gmail": {"configured": state["gmail"]["configured"], "synced_at": state["gmail"]["synced_at"]},
        }
        fingerprint = json.dumps(track, sort_keys=True, ensure_ascii=False)
        old_fp = None
        if os.path.exists(profile_path):
            try:
                old_fp = json.dumps(read_enc(profile_path, passphrase), sort_keys=True, ensure_ascii=False)
            except Exception:
                old_fp = None
        if fingerprint != old_fp:
            write_enc(profile_path, track, passphrase)
            log("track: profile.enc refreshed (%d application(s))" % len(track["applications"]))
    except Exception as exc:
        log("track: could not build profile.enc: %s" % exc)

    summary = outcomes.get("_summary") if outcomes else None
    if summary:
        log(autoapply.summarise(outcomes).strip())
    if args.dry_run:
        log("dry run: status written locally, nothing pushed")
        return 0
    # Push only when something other than the timestamp moved, so an idle
    # PC does not commit to the site branch every half hour.
    changed = bool(requests_) or bool(outcomes) or (
        json.dumps({k: v for k, v in (previous or {}).items() if k != "updated"}, sort_keys=True)
        != json.dumps({k: v for k, v in status.items() if k != "updated"}, sort_keys=True))
    profile_changed = subprocess.run(["git", "status", "--porcelain", "--", "data/apply/profile.enc"],
                                     cwd=pages, capture_output=True, text=True).stdout.strip() != ""
    if not changed and not profile_changed:
        log("nothing changed; not pushing")
        return 0
    subprocess.run([sys.executable, os.path.join(HERE, "pages_git.py"), "push", pages,
                    "auto-apply: %d request(s), %d applied today" % (len(queue_status), applied_today)], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
