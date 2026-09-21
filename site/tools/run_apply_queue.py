"""GitHub Actions entry point: put a phone's request on the queue for the PC.

Inputs come from the environment (set by .github/workflows/apply.yml):
    INPUT_ACTION      queue | remove | retry | pause | resume | settings |
                      answers | profile | notes   (apply = old name for queue)
    INPUT_PAYLOAD     JSON. By action:
                        queue     {report, jobs: "all" | [keys]}  or  {items: [job dicts]}
                        remove    {keys: [...]}       retry  {keys: [...]}
                        settings  {auto: {enabled, min_score, boards}, limit, offsite}
                        answers   {question: answer}
                        profile   the answers form     notes  {job_id: {status, note}}
    INPUT_REPORT / INPUT_JOBS / INPUT_ANSWERS   old-style inputs, still accepted
    INPUT_NOTE        free text
    PAGES_REPO_URL    push URL for the gh-pages branch (set by the workflow)

Writes data/apply/queue/<stamp>-<action>.json on gh-pages. The PC-side worker
(site/tools/phone_apply.py) folds it into data/apply/queue.json, the one queue.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

ACTIONS = {"queue", "apply", "remove", "retry", "pause", "resume", "settings", "answers", "profile", "notes"}


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def main():
    action = env("INPUT_ACTION", "queue")
    if action not in ACTIONS:
        raise SystemExit("unknown action %r" % action)
    if action == "apply":
        action = "queue"
    now = datetime.now(timezone.utc)
    request = {"type": action, "requested_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "note": env("INPUT_NOTE")}
    raw = env("INPUT_PAYLOAD")
    payload = {}
    if raw:
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise SystemExit("payload must be JSON: %s" % exc)
        if not isinstance(payload, dict):
            raise SystemExit("payload must be a JSON object")
    if action == "queue":
        if not payload:
            report = env("INPUT_REPORT")
            if not report:
                raise SystemExit("queue needs a payload with report+jobs or items")
            jobs = env("INPUT_JOBS", "all")
            payload = {"report": report, "jobs": "all" if jobs.lower() == "all" else [j.strip() for j in jobs.split(",") if j.strip()]}
        if not (payload.get("report") or payload.get("items")):
            raise SystemExit("queue needs report+jobs or items")
    elif action == "answers":
        if not payload:
            try:
                payload = json.loads(env("INPUT_ANSWERS") or "{}")
            except ValueError as exc:
                raise SystemExit("answers must be a JSON object: %s" % exc)
        if not payload:
            raise SystemExit("answers must be a non-empty JSON object")
        payload = {str(k): str(v) for k, v in payload.items()}
        request["answers"] = payload
    elif action in ("remove", "retry", "settings", "profile", "notes") and not payload:
        raise SystemExit("%s needs a payload" % action)
    request["payload"] = payload

    work = os.path.abspath(env("RUNNER_TEMP", "work"))
    pages = os.path.join(work, "pages")
    py = [sys.executable]
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "checkout", pages], check=True)
    queue_dir = os.path.join(pages, "data", "apply", "queue")
    os.makedirs(queue_dir, exist_ok=True)
    name = "%s-%s.json" % (now.strftime("%Y%m%d-%H%M%S"), action)
    with open(os.path.join(queue_dir, name), "wb") as f:
        f.write(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "push", pages,
                         "phone request: %s%s" % (action, (" " + str(payload.get("report", ""))) if action == "queue" else "")],
                   check=True)
    print("queued %s -> data/apply/queue/%s" % (action, name))


if __name__ == "__main__":
    main()
