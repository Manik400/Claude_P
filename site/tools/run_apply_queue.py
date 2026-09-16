"""GitHub Actions entry point: put a phone's auto-apply request on the queue.

Inputs come from the environment (set by .github/workflows/apply.yml):
    INPUT_ACTION      apply | answers
    INPUT_REPORT      report id (apply): whose postings
    INPUT_JOBS        "all" or comma-separated LinkedIn job ids (apply)
    INPUT_ANSWERS     JSON {question: answer} (answers)
    INPUT_NOTE        free text
    SITE_PASSPHRASE   encrypts the queue file (repo secret)
    PAGES_REPO_URL    push URL for the gh-pages branch (set by the workflow)

Writes data/apply/queue/<stamp>-<action>.enc on gh-pages. The PC-side poller
(site/tools/phone_apply.py) reads it, applies, and publishes data/apply/status.enc.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vault  # noqa: E402


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def main():
    passphrase = vault.get_passphrase()
    if not passphrase:
        raise SystemExit("SITE_PASSPHRASE secret is missing")
    action = env("INPUT_ACTION", "apply")
    now = datetime.now(timezone.utc)
    request = {"type": action, "requested_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "note": env("INPUT_NOTE")}
    if action == "apply":
        report = env("INPUT_REPORT")
        if not report:
            raise SystemExit("report id is required for an apply request")
        raw = env("INPUT_JOBS", "all")
        request["report"] = report
        request["jobs"] = "all" if raw.lower() == "all" else [j.strip() for j in raw.split(",") if j.strip()]
    elif action == "answers":
        try:
            answers = json.loads(env("INPUT_ANSWERS") or "{}")
        except ValueError as exc:
            raise SystemExit("answers must be a JSON object: %s" % exc)
        if not isinstance(answers, dict) or not answers:
            raise SystemExit("answers must be a non-empty JSON object")
        request["answers"] = {str(k): str(v) for k, v in answers.items()}
    else:
        raise SystemExit("unknown action %r" % action)

    work = os.path.abspath(env("RUNNER_TEMP", "work"))
    pages = os.path.join(work, "pages")
    py = [sys.executable]
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "checkout", pages], check=True)
    queue_dir = os.path.join(pages, "data", "apply", "queue")
    os.makedirs(queue_dir, exist_ok=True)
    name = "%s-%s.enc" % (now.strftime("%Y%m%d-%H%M%S"), action)
    with open(os.path.join(queue_dir, name), "wb") as f:
        f.write(vault.encrypt_bytes(json.dumps(request, ensure_ascii=False).encode("utf-8"), passphrase))
    subprocess.run(py + [os.path.join(HERE, "pages_git.py"), "push", pages,
                         "apply request: %s%s" % (action, (" " + request.get("report", "")) if action == "apply" else "")],
                   check=True)
    print("queued %s -> data/apply/queue/%s" % (action, name))


if __name__ == "__main__":
    main()
