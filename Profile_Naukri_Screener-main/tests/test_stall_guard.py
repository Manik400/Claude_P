"""naukri/jobs/stall_guard.py - a hung pass ends the process; a sleeping loop is left alone."""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, timeout: float = 60):
    t = time.time()
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return p.returncode, time.time() - t, p.stdout + p.stderr


def test_armed_and_silent_process_is_killed():
    rc, took, _out = _run("""
import time
from naukri.jobs.stall_guard import StallGuard
g = StallGuard("t", check_every=0.5)
g.arm(1)              # arm() floors this at 30 s
time.sleep(120)       # a hung pass
print("not killed")
""", timeout=90)
    assert rc != 0, rc          # taskkill takes the tree down (exit 1) before os._exit(3) gets its turn
    assert 25 < took < 75, took


def test_disarmed_process_lives_and_exits_normally():
    rc, _took, out = _run("""
import time
from naukri.jobs.stall_guard import StallGuard
g = StallGuard("t", check_every=0.2)
g.arm(1)
g.disarm()
time.sleep(2)
print("alive")
""")
    assert rc == 0 and "alive" in out
