"""One-off: two company-site 'applied' rows were contact / quote forms, not applications.

Waits for the apply lock (so a running apply pass cannot overwrite the change), sets
the two ledger rows back to 'offsite' with a retry mark, then releases every posting
the fixed applier gave up on (career_apply.release_failed) and the queue's by-hand
items (phone_apply.retry_by_hand).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "site" / "tools"))

from naukri.jobs import career_apply  # noqa: E402
from naukri.jobs.ledger import Ledger  # noqa: E402
from naukri.jobs.runlock import RunLock  # noqa: E402

WRONG = {
    "250926504180": "Loop Methods - 'Send Your Resume' quote form, not an application",
    "140926500967": "Createntropy - 'Get In Touch' contact form; the site said 'Failed to submit'",
}


def main() -> int:
    lock = RunLock()
    print("waiting for the apply lock (a run is in progress)...", flush=True)
    if not lock.acquire(wait_s=3 * 3600, poll_s=15):
        print("could not get the lock in 3 h; nothing changed")
        return 1
    try:
        ledger = Ledger()
        for job_id, why in WRONG.items():
            entry = ledger.entries.get(job_id)
            if entry and entry.get("status") == "applied":
                entry["status"] = "offsite"
                entry["note"] = "retry requested: " + why
                print("ledger: %s -> offsite (%s)" % (job_id, why))
        # every other "form closed, no thank-you text" verdict from the first run of the new
        # applier (22:48 on): each one checked so far was a contact / quote form on the
        # company's home page, never the application - the contact-form rule now stops those
        for job_id, entry in ledger.entries.items():
            if entry.get("status") == "applied" and "form closed, no thank-you text" in str(entry.get("note", "")) \
                    and str(entry.get("at", "")) >= "2026-09-27T22:48":
                entry["status"] = "offsite"
                entry["note"] = "retry requested: filled a contact form, not the application (" + entry["note"][len("company site: "):]
                print("ledger: %s -> offsite (%s @ %s)" % (job_id, entry.get("title"), entry.get("company")))
        ledger.save()
        counts = career_apply.release_failed()
        print("released: %d worldwide-board, %d Naukri, %d LinkedIn posting(s); %d kept" % (
            counts["web"], counts["naukri"], counts["linkedin"], counts["kept"]))
        import phone_apply
        n = phone_apply.retry_by_hand()
        print("queue: %d by-hand item(s) back in line" % n)
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
