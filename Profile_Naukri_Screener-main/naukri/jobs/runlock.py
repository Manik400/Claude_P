"""One apply pass at a time on this PC.

Two scheduled tasks apply (PhoneApplyQueue every 30 min, JobHuntApply after
each round) and both open the same Chrome profile. When they overlap, the
second Chrome exits at once (profile in use) and that run dies at launch -
the queue then showed a crash where an application should have been. This
lock makes the second run wait its turn, or step aside for this run when the
wait is too long.

The lock is an OS-level file lock (msvcrt / fcntl), so a run that crashes or
is killed releases it by itself; nothing stale is left behind.
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


_HELD: dict = {}         # path -> depth, for the process that holds it (re-entrant within one process)


class RunLock:
    def __init__(self, path: Path = LOCK_PATH):
        self.path = path
        self._fh = None
        self._nested = False

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
            fh.write("%d %s\n" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")))
            fh.flush()
        except OSError:
            pass
        self._fh = fh
        _HELD[self.path] = 1
        try:    # who holds it, readable by others (the locked file itself cannot be read while locked)
            self.path.with_suffix(".holder").write_text("%d %s\n" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")), encoding="utf-8")
        except OSError:
            pass
        return True

    def acquire(self, wait_s: int = DEFAULT_WAIT_S, poll_s: int = 20) -> bool:
        """Wait up to `wait_s` for the other run to finish. False when it did not."""
        deadline = time.monotonic() + wait_s
        told = False
        while True:
            if self.try_acquire():
                return True
            if time.monotonic() >= deadline:
                return False
            if not told:
                log.info("another apply run is in progress (%s) - waiting up to %d min for it", self.holder(), wait_s // 60)
                told = True
            time.sleep(poll_s)

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
