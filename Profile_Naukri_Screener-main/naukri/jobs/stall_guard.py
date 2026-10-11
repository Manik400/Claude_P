"""A long-running loop that stops making progress is killed, so Task Scheduler starts a
fresh one - instead of a hung process that keeps its task "Running" for ever.

    guard = StallGuard("live_feed")
    while True:
        guard.arm(20 * 60)        # this pass may take 20 minutes at most
        tick()
        guard.disarm()            # sleeping between passes is not a stall
        nap(...)

The four all-day loops (live feed, LinkedIn Premium, the two posts watchers) run
Playwright and HTTP calls that can, rarely, wait for ever: a page that never fires
its load event, a socket on a hotspot that went away mid-request. Their tasks are
-MultipleInstances IgnoreNew with no time limit, so a hung process was never
replaced and nothing it did (feed, drafts, posts) moved again until a reboot.

The guard is a daemon thread reading the wall clock every 30 s: past the armed
deadline it flushes the log, kills this process tree (the browser with it) and
exits 3. Wall clock, so a laptop that slept through the deadline settles it on
waking. Nothing is armed between passes.
"""
from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("naukri.jobs.stall_guard")


class StallGuard:
    def __init__(self, name: str, check_every: float = 30.0):
        self.name = name
        self.deadline: float | None = None
        self.note = ""
        self._check_every = check_every
        t = threading.Thread(target=self._watch, name=f"stall-guard-{name}", daemon=True)
        t.start()

    def arm(self, seconds: float, note: str = "") -> None:
        """This pass must be done within `seconds` of now."""
        self.note = note
        self.deadline = time.time() + max(30.0, seconds)

    def extend(self, seconds: float) -> None:
        """More time for a pass that is known to be long (counted from now)."""
        if self.deadline is not None:
            self.deadline = max(self.deadline, time.time() + seconds)

    def disarm(self) -> None:
        self.deadline = None

    def _watch(self) -> None:
        while True:
            time.sleep(self._check_every)
            dl = self.deadline
            if dl is None or time.time() < dl:
                continue
            log.error("%s: no progress for the whole allowed time%s - this process is hung; stopping it (and its browser) "
                      "so Task Scheduler starts a fresh one", self.name, f" ({self.note})" if self.note else "")
            for h in logging.getLogger().handlers:
                try:
                    h.flush()
                except Exception:  # noqa: BLE001
                    pass
            try:
                from .runlock import _kill_tree
                _kill_tree(os.getpid())          # children first: Chrome, node, the model
            except Exception:  # noqa: BLE001
                pass
            os._exit(3)
