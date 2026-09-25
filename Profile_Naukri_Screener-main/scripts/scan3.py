"""The three daily scans - last 24h, early, all jobs - then publish to the phone.

    python scripts/scan3.py             run all three, then publish
    python scripts/scan3.py --catchup   run only the scans the current slot is
                                        still missing, then publish

Slots are 10:00 and 16:00. A scan counts as done for a slot when an openings
page of its kind (read from the page <title>, see naukri/jobs/page.py
scan_kind) was written today after the slot started. So opening the laptop at
13:00 after sleeping through 10:00 runs the 10:00 scans; opening it again at
14:00 finds them done and only re-publishes; at 17:00 it runs the 16:00 ones.
Before 10:00 there is no slot due and --catchup does nothing.

A lock file keeps two runs (the scheduled one and a wake-up catch-up) from
driving the same browser profile at once - that crashes both.
"""
import argparse
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "data" / "jobs"
LOCK = ROOT / "data" / "scan3.lock"
SLOTS = ("10:00", "16:00")
STALE_LOCK_S = 4 * 3600

SCANS = [
    ("Last 24h", ["--posted-days", "1", "--new-only"]),
    ("Early", ["--early"]),
    ("All jobs", []),
]


def python():
    for p in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT.parent / "venv" / "Scripts" / "python.exe"):
        if p.exists():
            return str(p)
    return sys.executable


def current_slot(now):
    """Start of the latest slot at or before `now`, or None before the first."""
    due = [now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
           for h, m in (s.split(":") for s in SLOTS)]
    due = [d for d in due if d <= now]
    return due[-1] if due else None


def done_kinds(since):
    day = since.date().isoformat()
    kinds = set()
    for page in JOBS.glob(f"openings-{day}-r*.html"):
        if datetime.fromtimestamp(page.stat().st_mtime) < since:
            continue
        head = page.read_text(encoding="utf-8", errors="ignore")[:4096]
        m = re.search(r"<title>[^<]*? - ([^<]+)</title>", head)
        if m:
            kinds.add(m.group(1).strip())
    return kinds


def wait_for_network(limit_s=300):
    """Right after wake-up Wi-Fi is often not back yet; the scan would fail."""
    end = time.time() + limit_s
    while time.time() < end:
        try:
            socket.create_connection(("www.naukri.com", 443), timeout=5).close()
            return True
        except OSError:
            time.sleep(15)
    return False


def take_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        if LOCK.exists() and time.time() - LOCK.stat().st_mtime > STALE_LOCK_S:
            LOCK.unlink()
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catchup", action="store_true")
    args = ap.parse_args()

    now = datetime.now()
    todo = SCANS
    if args.catchup:
        slot = current_slot(now)
        if slot is None:
            print("scan3: no slot due yet today (first is %s)" % SLOTS[0])
            return 0
        have = done_kinds(slot)
        todo = [s for s in SCANS if s[0] not in have]
        print("scan3: slot %s - done: %s - missing: %s" % (
            slot.strftime("%H:%M"), ", ".join(sorted(have)) or "none",
            ", ".join(k for k, _ in todo) or "none"))

    if not take_lock():
        print("scan3: another scan run is in progress - leaving it to finish")
        return 0
    try:
        if not wait_for_network():
            print("scan3: no network after 5 minutes - giving up; the next wake-up retries")
            return 1
        failed = 0
        for i, (kind, flags) in enumerate(todo, 1):
            print("----- scan %d of %d: %s -----" % (i, len(todo), kind), flush=True)
            cmd = [python(), "main.py", "--jobs-export", "--top", "60", *flags, "--apply-found", "--yes"]
            rc = 1
            # Wi-Fi drops mid-run are common on the laptop: a scan that fails is
            # retried once the network is back, instead of losing that page.
            for attempt in (1, 2):
                if not wait_for_network():
                    print("scan3: no network - skipping %s; the next reconnect catches it up" % kind)
                    break
                rc = subprocess.call(cmd, cwd=ROOT)
                if rc == 0:
                    break
                if attempt == 1:
                    print("scan3: %s failed (exit %d) - retrying in 2 minutes" % (kind, rc), flush=True)
                    time.sleep(120)
            failed |= rc != 0
        # Relearn from today's outcomes and rebuild the accuracy page, so the
        # next scan scores with it and the phone shows today's numbers.
        print("----- accuracy & learning -----", flush=True)
        failed |= subprocess.call([python(), "main.py", "--accuracy"], cwd=ROOT) != 0
        # Always publish: a page written earlier but never pushed (offline at the
        # time) goes up now. phone_publish skips what the site already has.
        print("----- publish to phone -----", flush=True)
        failed |= subprocess.call(["cmd", "/c", "publish_to_phone.bat", "--max", "6"], cwd=ROOT) != 0
        return 1 if failed else 0
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
