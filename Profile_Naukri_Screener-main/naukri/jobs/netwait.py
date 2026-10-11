"""Is the internet there, and waiting until it is - for the all-day loops.

    from .netwait import online, wait_for_network, NETWORK_ERROR_RX

    if not online():
        wait_for_network(stop=lambda: code_changed(stamp))    # returns the moment it is back
    try:
        run_once()
    except Exception as exc:
        if NETWORK_ERROR_RX.search(str(exc)):                   # the hotspot went away mid-pass
            ...retry as soon as wait_for_network() returns, not after the normal gap

The PC's internet is a phone hotspot that comes and goes. A pass that starts
offline fails at its first page and used to leave "pass failed: net::ERR_INTERNET_
DISCONNECTED" on the phone until the next scheduled pass - hours later. Now a loop
waits (checking every 20 s) and continues within seconds of the network returning.
"""
from __future__ import annotations

import logging
import re
import socket
import time
from datetime import datetime

log = logging.getLogger("naukri.jobs.netwait")

# TCP only - hotspots often block ICMP. Any one answering is enough.
HOSTS = (("api.github.com", 443), ("www.linkedin.com", 443), ("www.naukri.com", 443), ("1.1.1.1", 443))
NETWORK_ERROR_RX = re.compile(r"net::ERR_|ERR_INTERNET_DISCONNECTED|ERR_NAME_NOT_RESOLVED|ERR_CONNECTION|ERR_NETWORK|"
                              r"Timeout \d+ms exceeded|ConnectionError|Connection reset|getaddrinfo|NameResolutionError|"
                              r"Max retries exceeded|Network is unreachable|Temporary failure in name resolution", re.I)


def online(timeout: float = 4.0) -> bool:
    for host, port in HOSTS:
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


def wait_for_network(max_s: float = 6 * 3600, poll_s: float = 20.0, stop=None, what: str = "") -> bool:
    """Block until the internet answers (True), `max_s` passes (False) or `stop()` says so (False).
    Logs once when the wait starts and once when it ends."""
    if online():
        return True
    since = datetime.now()
    log.warning("no internet%s - waiting for it (checking every %.0f s)", f" ({what})" if what else "", poll_s)
    end = time.time() + max_s
    while time.time() < end:
        if stop is not None and stop():
            return False
        time.sleep(poll_s)
        if online():
            gone = (datetime.now() - since).total_seconds() / 60
            log.info("internet is back after %.0f min (since %s) - continuing now", gone, since.strftime("%H:%M"))
            return True
    log.warning("still no internet after %.0f min - giving up this wait", max_s / 60)
    return False


def offline_note(since: datetime | None = None) -> str:
    """One line for the phone: what is wrong, since when, what happens next."""
    when = (since or datetime.now()).strftime("%H:%M")
    return f"no internet since {when} (the hotspot?) - waiting; continues the moment it is back"
