"""Run one scheduled task's command and leave NOTHING running after it.

    set JOBGUARD_CMD=<command line>  &&  python scripts\\jobguard.py

run_hidden.vbs starts every scheduled task (JobHuntApply, PhoneApplyQueue,
NaukriJobAgent-Scan3, ...) through this. The guard puts itself in a Windows
Job Object with KILL_ON_JOB_CLOSE and then starts the command; every process
the run creates - cmd, the batch's powershell, Python, Playwright's node
driver, Chrome / Chromium and all their children - joins that job. When this
process ends for any reason (the run finished, crashed, or Task Scheduler's
time limit killed it) Windows closes the job and kills whatever is still in
it. Before this, a finished run could leave a dozen headless browsers behind,
holding the Simplify profile locked so the next run waited 15 minutes for it.

The command line comes in an environment variable rather than as arguments,
so the vbs's cmd /S /C "... >> log 2>&1" quoting reaches CreateProcess as is.
Exits with the command's exit code.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x20
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
JobObjectExtendedLimitInformation = 9
# Committed memory the whole run (Python, model, headless browsers) may hold.
# Past it allocations fail inside the run only, instead of the PC hitting its
# commit limit and every app crashing. JOBGUARD_MAX_MB=0 turns the cap off.
JOB_MEMORY_MB = int(os.environ.get("JOBGUARD_MAX_MB") or 6144)


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def kill_tree_on_exit() -> bool:
    """Join a kill-on-close job; children started afterwards join it too.

    The handle is never closed here on purpose: the OS closes it when this
    process ends, and that is what takes the whole tree down.
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PRIORITY_CLASS
    # Background runs yield the CPU to whatever you are doing in the foreground.
    info.BasicLimitInformation.PriorityClass = BELOW_NORMAL_PRIORITY_CLASS
    if JOB_MEMORY_MB > 0:
        info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY
        info.JobMemoryLimit = JOB_MEMORY_MB * 1024 * 1024
    if not k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                       ctypes.byref(info), ctypes.sizeof(info)):
        return False
    if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        return False
    kill_tree_on_exit.handle = job  # keep it referenced for the life of the process
    return True


def wait_for_turn() -> None:
    """Let one scheduled run work at a time instead of all of them together.

    Every task's run takes the same machine-wide mutex; the next one waits for
    it, up to JOBGUARD_WAIT_MIN minutes (default 10), and then starts anyway, so
    no run is ever skipped - JobHuntApply re-arms its own next trigger from its
    batch, and a skipped round would never set it. Windows releases the mutex
    when this process ends, however it ends. Nothing is held on failure.
    """
    wait_min = float(os.environ.get("JOBGUARD_WAIT_MIN") or 10)
    if wait_min <= 0:
        return
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    mutex = k32.CreateMutexW(None, False, "Global\\NaukriJobGuardOneRun")
    if not mutex:
        return
    wait_for_turn.handle = mutex  # owned (if acquired) until this process exits
    rc = k32.WaitForSingleObject(mutex, int(wait_min * 60_000))
    if rc == 0x102:  # WAIT_TIMEOUT
        print(f"jobguard: another scheduled run still busy after {wait_min:g} min - "
              "starting anyway", file=sys.stderr)


def main() -> int:
    cmd = os.environ.pop("JOBGUARD_CMD", "")
    if not cmd:
        print("jobguard: JOBGUARD_CMD is empty", file=sys.stderr)
        return 2
    wait_for_turn()
    if not kill_tree_on_exit():  # still run the task; only the cleanup is lost
        print(f"jobguard: no job object (error {ctypes.get_last_error()}) - "
              "processes may outlive this run", file=sys.stderr)
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
