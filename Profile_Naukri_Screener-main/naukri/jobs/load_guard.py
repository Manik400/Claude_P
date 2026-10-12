"""Keep the background work polite: low CPU priority, and the heavy local model only when the PC can spare it.

    from .load_guard import background_priority, pc_is_free, wait_until_free
    background_priority("idle")          # this process yields the CPU to anything you are doing
    if not pc_is_free(): ...             # a job-hunt run in progress, little free RAM, or you are at the keyboard
    wait_until_free(release=localai.release, stop=lambda: code_changed(stamp))

Written 2026-10-12 after the PC sat at 31 of 32 GB RAM with 7,800 page faults a second:
the post labeler ran the 12 GB model with 10 threads around the clock and held the
machine-wide model lock for 3-7 minutes a post, so the runs that matter (form answers,
tailored resumes, drafts) queued behind it. The labeler now only works when the PC is
free; the live feed uses the small model; every all-day loop runs at reduced priority.
"""
from __future__ import annotations

import ctypes
import logging
import os
import time
from ctypes import wintypes

log = logging.getLogger("naukri.jobs.load_guard")

_PRIORITY = {"idle": 0x40, "below": 0x4000, "normal": 0x20}
MIN_FREE_GB = float(os.environ.get("LOAD_GUARD_MIN_FREE_GB") or 6)
IDLE_SECONDS = float(os.environ.get("LOAD_GUARD_IDLE_SECONDS") or 180)


def background_priority(level: str = "below") -> None:
    """Set this process (and the browsers / model threads it starts) to a lower CPU priority."""
    if os.name != "nt":
        try:
            os.nice(10 if level == "below" else 19)
        except OSError:
            pass
        return
    try:
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), _PRIORITY.get(level, 0x4000))
    except Exception as exc:  # noqa: BLE001
        log.debug("priority not set: %s", exc)


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_ram_gb() -> float:
    if os.name != "nt":
        try:
            return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
        except (ValueError, OSError):
            return 99.0
    st = _MemStatus()
    st.dwLength = ctypes.sizeof(st)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return 99.0
    return st.ullAvailPhys / 2 ** 30


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def user_idle_seconds() -> float:
    """Seconds since the last keyboard / mouse input in this session (0 when it cannot be read)."""
    if os.name != "nt":
        return 1e9
    li = _LastInput()
    li.cbSize = ctypes.sizeof(li)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    return max(0.0, (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0)


def heavy_run_active() -> bool:
    """A scheduled job-hunt run (hourly round, a Naukri scan, the phone queue) is in progress:
    the jobguard mutex is held, or the apply lock is."""
    if os.name == "nt":
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenMutexW.restype = wintypes.HANDLE
            h = k32.OpenMutexW(0x00100000, False, "Global\\NaukriJobGuardOneRun")     # SYNCHRONIZE
            if h:
                try:
                    rc = k32.WaitForSingleObject(h, 0)
                    if rc in (0, 0x80):             # we got it (free, or its last owner died): give it straight back
                        k32.ReleaseMutex(h)
                    elif rc == 0x102:               # WAIT_TIMEOUT: a run holds it
                        return True
                finally:
                    k32.CloseHandle(h)
        except Exception as exc:  # noqa: BLE001
            log.debug("jobguard mutex not read: %s", exc)
    try:
        from .runlock import busy
        return busy()
    except Exception:  # noqa: BLE001
        return False


def pc_is_free(need_idle_user: bool = True) -> tuple[bool, str]:
    """(free, why not) - free = no job-hunt run, enough RAM, and (optionally) you away from the keyboard."""
    if heavy_run_active():
        return False, "a job-hunt run is in progress"
    ram = free_ram_gb()
    if ram < MIN_FREE_GB:
        return False, f"only {ram:.1f} GB RAM free"
    if need_idle_user:
        idle = user_idle_seconds()
        if idle < IDLE_SECONDS:
            return False, "you are using the PC"
    return True, ""


def wait_until_free(release=None, stop=None, poll_s: float = 60.0, need_idle_user: bool = True, what: str = "") -> bool:
    """Block until pc_is_free() (True) or stop() (False). Unloads the model (`release`) while it waits,
    so the waiting process holds no RAM for it. Logs once when it starts waiting and once when it resumes."""
    free, why = pc_is_free(need_idle_user)
    if free:
        return True
    if release is not None:
        try:
            release()
        except Exception:  # noqa: BLE001
            pass
    since = time.time()
    log.info("%spausing: %s - continuing when the PC is free", f"{what}: " if what else "", why)
    while True:
        if stop is not None and stop():
            return False
        time.sleep(poll_s)
        free, why = pc_is_free(need_idle_user)
        if free:
            log.info("%sPC is free again after %.0f min - continuing", f"{what}: " if what else "", (time.time() - since) / 60)
            return True
