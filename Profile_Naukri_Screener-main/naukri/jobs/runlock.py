"""One apply pass at a time on this PC.

Two scheduled tasks apply (PhoneApplyQueue every 30 min, JobHuntApply after
each round) and both open the same Chrome profile. When they overlap, the
second Chrome exits at once (profile in use) and that run dies at launch -
the queue then showed a crash where an application should have been. This
lock makes the second run wait its turn, or step aside for this run when the
wait is too long.

The lock is an OS-level file lock (msvcrt / fcntl), so a run that crashes or
is killed releases it by itself. A run that HANGS keeps it, though: one scan
froze inside a company-site page and held the lock for 5+ hours, so every
queue run stepped aside and the phone said "PC off". A holder is stopped, with
its browser, once it is past the end it announced (apply.holder carries
`ends=<epoch>`: the run's own time limit plus its watchdog grace) - or, for a
holder that announced none, older than APPLY_LOCK_STALE_MIN (default 180 min).
Both are wall-clock checks, so a PC that slept through the holder's limit
settles it on the first wait after waking up.

A waiter also leaves apply.wanted (pid, time, project) while it waits. A long
apply pass checks it between applications and, when the waiter is the phone
queue - your own picks - stops early and hands the browser over.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger("naukri.jobs.runlock")

ROOT = Path(__file__).resolve().parent.parent.parent
LOCK_PATH = ROOT / "data" / "jobs" / "apply.lock"
DEFAULT_WAIT_S = int(os.environ.get("APPLY_LOCK_WAIT") or 1500)     # 25 min
STALE_S = int(float(os.environ.get("APPLY_LOCK_STALE_MIN") or 180) * 60)
# Past its announced end by this much, a holder is taken for hung.
ENDS_GRACE_S = 5 * 60
# apply.wanted older than this is a waiter that gave up or was killed.
WANTED_FRESH_S = 40 * 60


def _process_started(pid: int) -> float | None:
    """Epoch seconds the process started, or None when it is not running."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        try:
            return os.stat("/proc/%d" % pid).st_mtime
        except OSError:
            return 0.0
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:   # 259 = STILL_ACTIVE
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
            return 0.0
        ft = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return ft / 1e7 - 11644473600
    finally:
        k32.CloseHandle(h)


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        import subprocess
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            os.kill(pid, signal.SIGKILL)


_HELD: dict = {}         # path -> depth, for the process that holds it (re-entrant within one process)


class RunLock:
    def __init__(self, path: Path = LOCK_PATH, ends_at: float | None = None, project: str = ""):
        """`ends_at`: epoch seconds by which this run will have stopped on its own
        (its time limit plus watchdog grace); announced to waiters, who stop this
        run once it is past it. `project` ("phone" for the phone queue) is what
        the holder sees in apply.wanted while this run waits."""
        self.path = path
        self.ends_at = ends_at
        self.project = project or ""
        self._fh = None
        self._nested = False

    @property
    def wanted_path(self) -> Path:
        return self.path.with_suffix(".wanted")

    def _stamp(self) -> str:
        line = "%d %s" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S"))
        if self.ends_at:
            line += " ends=%d" % int(self.ends_at)
        return line + "\n"

    def try_acquire(self) -> bool:
        if _HELD.get(self.path):
            # this process already holds it (phone_apply around autoapply.run): count, don't lock twice
            _HELD[self.path] += 1
            self._nested = True
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(self._stamp())
            fh.flush()
        except OSError:
            pass
        self._fh = fh
        _HELD[self.path] = 1
        try:    # who holds it, readable by others (the locked file itself cannot be read while locked)
            self.path.with_suffix(".holder").write_text(self._stamp(), encoding="utf-8")
        except OSError:
            pass
        return True

    def acquire(self, wait_s: int = DEFAULT_WAIT_S, poll_s: int = 20) -> bool:
        """Wait up to `wait_s` for the other run to finish. False when it did not.

        Wall-clock wait: a PC that sleeps while this waits gives up at the same
        clock time it would have, not `sleep time` later.
        """
        deadline = time.time() + wait_s
        told = False
        try:
            while True:
                if self.try_acquire():
                    return True
                if self.break_stale():
                    continue
                if time.time() >= deadline:
                    return False
                if not told:
                    log.info("another apply run is in progress (%s) - waiting up to %d min for it", self.holder(), wait_s // 60)
                    told = True
                    self._want()
                time.sleep(poll_s)
        finally:
            self._unwant()

    def _want(self) -> None:
        try:
            self.wanted_path.write_text("%d %d %s\n" % (os.getpid(), int(time.time()), self.project or "-"), encoding="utf-8")
        except OSError:
            pass

    def _unwant(self) -> None:
        try:
            parts = self.wanted_path.read_text(encoding="utf-8").split()
            if parts and parts[0] == str(os.getpid()):
                self.wanted_path.unlink()
        except OSError:
            pass

    def wanted_by(self) -> str:
        """Project of a live run waiting for the lock right now ("phone", ...), or ""."""
        try:
            parts = self.wanted_path.read_text(encoding="utf-8").split()
        except OSError:
            return ""
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit() or parts[0] == str(os.getpid()):
            return ""
        if time.time() - int(parts[1]) > WANTED_FRESH_S or _process_started(int(parts[0])) is None:
            return ""
        return parts[2] if parts[2] != "-" else "other"

    def break_stale(self, stale_s: int = STALE_S) -> bool:
        """Stop the holder when it is past its announced end, or has held the lock
        longer than `stale_s`. True if it was stopped."""
        parts = self.holder().split()
        if len(parts) < 3 or not parts[0].isdigit() or parts[0] == str(os.getpid()):
            return False
        try:
            since = time.mktime(time.strptime(parts[1] + " " + parts[2], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            return False
        ends = None
        for extra in parts[3:]:
            if extra.startswith("ends=") and extra[5:].isdigit():
                ends = int(extra[5:])
        if ends is not None:
            if time.time() < ends + ENDS_GRACE_S:
                return False
        elif time.time() - since < stale_s:
            return False
        pid = int(parts[0])
        started = _process_started(pid)
        # Not running, or the pid now belongs to a process started after the lock was taken.
        if started is None or started > since + 60:
            return False
        log.warning("apply lock held by %s for %d min%s - that run is hung; stopping it (and its browser)",
                    self.holder(), (time.time() - since) // 60,
                    "" if ends is None else " (its own limit passed at %s)" % time.strftime("%H:%M", time.localtime(ends)))
        _kill_tree(pid)
        time.sleep(3)
        return True

    def holder(self) -> str:
        try:
            return self.path.with_suffix(".holder").read_text(encoding="utf-8").strip() or "unknown"
        except OSError:
            return "unknown"

    def release(self) -> None:
        if self._nested:
            self._nested = False
            _HELD[self.path] = max(0, _HELD.get(self.path, 1) - 1)
            return
        fh, self._fh = self._fh, None
        if fh is None:
            return
        _HELD.pop(self.path, None)
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release()


def busy() -> bool:
    """Is an apply pass running right now? (Takes and drops the lock.)"""
    lock = RunLock()
    if lock.try_acquire():
        lock.release()
        return False
    return True
