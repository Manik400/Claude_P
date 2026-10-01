"""The day's three scans - last 24h, early, all jobs - each ONCE a day, then publish.

    python scripts/scan3.py             run whichever of the three has not run
                                        today, if it is between 10:00 and 23:00
    python scripts/scan3.py --force     run all three now, whatever the time

These three are the only scans of the day. Task Scheduler checks every 30
minutes from 10:00 to 23:00 and on wake / logon / unlock / network reconnect
(scripts/schedule_jobs_agent.ps1 -Mode scan3); a check that finds all three
done today exits at once, so nothing runs twice in a day. A sleeping laptop
is not woken - the first check after it wakes up runs what is missing.

A scan counts as done once it has finished (data/jobs/scan3_done.json), or
when today already has an openings page of its kind (read from the page
<title>, see naukri/jobs/page.py scan_kind). A scan that fails is retried at
the next check, at most MAX_TRIES times a day.

A lock file keeps two runs (a scheduled check and a wake-up one) from driving
the same browser profile at once - that crashes both.
"""
import argparse
import json
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
STATE = JOBS / "scan3_done.json"
WINDOW = ("10:00", "23:00")
MAX_TRIES = 3
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


def in_window(now):
    start, end = ([int(x) for x in t.split(":")] for t in WINDOW)
    return now.replace(hour=start[0], minute=start[1], second=0, microsecond=0) <= now         < now.replace(hour=end[0], minute=end[1], second=0, microsecond=0)


def load_state(day):
    """{"date", "done": {kind: time}, "tries": {kind: n}} for `day`; empty on a new day."""
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if state.get("date") == day:
            state.setdefault("done", {})
            state.setdefault("tries", {})
            return state
    except (OSError, ValueError, AttributeError):
        pass
    return {"date": day, "done": {}, "tries": {}}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def page_kinds(day):
    """Kinds that already have an openings page today."""
    kinds = set()
    for page in JOBS.glob(f"openings-{day}-r*.html"):
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


def _alive(pid: int) -> bool:
    """Is a process with this id still running?"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stale(lock: Path) -> bool:
    """Older than STALE_LOCK_S, or the run that wrote it is gone (killed, crashed,
    PC restarted) - a killed run otherwise blocked every check for four hours."""
    if time.time() - lock.stat().st_mtime > STALE_LOCK_S:
        return True
    try:
        return not _alive(int(lock.read_text().strip() or 0))
    except (OSError, ValueError):
        return False


def take_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        if LOCK.exists() and _stale(LOCK):
            LOCK.unlink()
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="run all three now, whatever the time")
    ap.add_argument("--catchup", action="store_true", help=argparse.SUPPRESS)   # old task arg; same as no flag
    args = ap.parse_args()

    now = datetime.now()
    day = now.date().isoformat()
    state = load_state(day)
    todo = SCANS
    if not args.force:
        if not in_window(now):
            print("scan3: %s is outside %s-%s - nothing to do" % (now.strftime("%H:%M"), *WINDOW))
            return 0
        have = set(state["done"]) | page_kinds(day)
        gave_up = {k for k, n in state["tries"].items() if n >= MAX_TRIES and k not in have}
        todo = [s for s in SCANS if s[0] not in have and s[0] not in gave_up]
        print("scan3: today done: %s - to run: %s%s" % (
            ", ".join(sorted(have)) or "none", ", ".join(k for k, _ in todo) or "none",
            " - given up after %d tries: %s" % (MAX_TRIES, ", ".join(sorted(gave_up))) if gave_up else ""))
        if not todo:
            return 0

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
                state["tries"][kind] = state["tries"].get(kind, 0) + 1
                save_state(state)
                rc = subprocess.call(cmd, cwd=ROOT)
                if rc == 0:
                    state["done"][kind] = datetime.now().isoformat(timespec="seconds")
                    save_state(state)
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
