"""One scheduled profile refresh: run it, write one line about it, keep a day.

    python scripts\\refresh_log.py            run main.py --refresh and log it
    python scripts\\refresh_log.py --prune    drop lines older than 24 h, say what went
    python scripts\\refresh_log.py --tail 20  last lines of the log

This is what refresh_profile.bat calls, which is what the 45-minute scheduled
task (scripts\\schedule_refresh.ps1) runs. It exists because the refresh itself
is silent about the one thing you want to know later: did the 05:15 run work?

    2026-09-18 05:15:02  ok  profile timestamp bumped (3.4s)
    2026-09-18 06:00:03  FAILED  session expired - run python main.py --login (6.1s)

WHY THE PRUNE COMES FIRST. A line every 45 minutes is 32 a day forever, so the
log is cut to the last 24 hours on every run - before the run, never after, so
the line this run is about to write can never be the one that gets dropped. A
missing, empty or briefly locked file is not an error here: the prune is
skipped and the run still logs. The rewrite is also abandoned if the file
changed while we were reading it, so a second refresh appending at that moment
does not lose its line - the next prune picks the old lines up anyway.

Exit code is main.py's own: 0 refreshed, 1 refresh failed, 2 session expired.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "logs" / "refresh.log"
KEEP = timedelta(hours=24)
STAMP = "%Y-%m-%d %H:%M:%S"
LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\b")

# The log is shared with whatever else happens to be running (the scan tasks
# also refresh), and on Windows a file being written is a file you cannot
# rename over. Every touch gets a few short retries before giving up.
ATTEMPTS = 6
PAUSE = 0.25


def _read_text() -> str | None:
    """The log's contents, or None if it is missing or cannot be read."""
    for n in range(ATTEMPTS):
        try:
            # utf-8-sig, not utf-8: PowerShell's Set-Content/Out-File leave a
            # BOM, and a BOM glued to the first timestamp makes that line
            # unparseable - which used to keep a three-day-old first line alive
            # forever while the lines under it were pruned correctly.
            return LOG_FILE.read_text(encoding="utf-8-sig", errors="replace")
        except FileNotFoundError:
            return None
        except OSError:
            time.sleep(PAUSE)
    return None


def append(line: str) -> bool:
    """Add one line to the log. Returns False only if the file stayed locked."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    for n in range(ATTEMPTS):
        try:
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line.rstrip("\n") + "\n")
            return True
        except OSError:
            time.sleep(PAUSE)
    return False


def prune(now: datetime | None = None) -> tuple[int, int]:
    """Drop lines older than 24 h. Returns (kept, dropped)."""
    now = now or datetime.now()
    cutoff = now - KEEP

    before = _read_text()
    if not before:
        return (0, 0)

    kept: list[str] = []
    dropped = 0
    keeping = True  # a line with no timestamp inherits the last verdict
    for line in before.splitlines():
        match = LINE_RE.match(line)
        if match:
            try:
                keeping = datetime.strptime(match.group(1), STAMP) >= cutoff
            except ValueError:
                keeping = True
        if keeping:
            kept.append(line)
        else:
            dropped += 1

    if not dropped:
        return (len(kept), 0)

    text = "".join(line + "\n" for line in kept)
    tmp = LOG_FILE.with_suffix(".log.tmp")
    for n in range(ATTEMPTS):
        try:
            # Re-read at the last moment: if someone appended while we worked,
            # leave the file alone rather than overwrite their line.
            if _read_text() != before:
                return (len(kept), 0)
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, LOG_FILE)
            return (len(kept), dropped)
        except OSError:
            time.sleep(PAUSE)
    try:
        tmp.unlink()
    except OSError:
        pass
    return (len(kept), 0)


def _verdict(code: int, output: str) -> tuple[str, str]:
    """Turn main.py's exit code into the words that go in the log."""
    if code == 0:
        return ("ok", "profile timestamp bumped")
    low = output.lower()
    if "--login" in low or "session has expired" in low or "no saved session" in low:
        return ("FAILED", "session expired - run python main.py --login")
    if code == 1:
        return ("FAILED", "refresh did not complete - see logs\\naukri.log")
    return ("FAILED", f"main.py --refresh exited {code} - see logs\\naukri.log")


def run_refresh() -> int:
    """Run the refresh, log one line about it, return its exit code."""
    started = time.monotonic()
    try:
        done = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--refresh"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        code = done.returncode
        output = (done.stdout or "") + (done.stderr or "")
    except Exception as exc:  # python missing, main.py gone, ...
        code = 1
        output = f"could not start main.py --refresh: {exc}"

    seconds = time.monotonic() - started
    # Keep the scheduled.log copy of the run intact - run_hidden.vbs captures
    # whatever this process prints, and that is where a traceback belongs.
    if output.strip():
        print(output.rstrip())

    status, detail = _verdict(code, output)
    line = f"{datetime.now().strftime(STAMP)}  {status}  {detail} ({seconds:.1f}s)"
    if not append(line):
        print(f"  Could not write {LOG_FILE} - {line}")
    else:
        print(f"  {line}")
    return code


def main(argv: list[str]) -> int:
    if "--tail" in argv:
        at = argv.index("--tail")
        count = int(argv[at + 1]) if len(argv) > at + 1 else 20
        text = _read_text() or ""
        print(f"  {LOG_FILE}")
        for line in text.splitlines()[-count:]:
            print(f"  {line}")
        return 0

    kept, dropped = prune()
    if "--prune" in argv:
        print(f"  {LOG_FILE}: kept {kept} line(s), dropped {dropped} older than 24 h")
        return 0
    return run_refresh()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
