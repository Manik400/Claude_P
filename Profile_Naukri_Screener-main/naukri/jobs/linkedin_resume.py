"""Sign in to the NEW LinkedIn account, then switch every LinkedIn service back on.

    python -m naukri.jobs.linkedin_resume            sign in (browser opens), then resume
    python -m naukri.jobs.linkedin_resume --no-login resume only (session already saved)

LinkedIn was switched off on 2026-10-15 and the old account's login deleted. The code is back
on since 2026-10-21; this script is the "login first, then start" step:

  1. opens a clean browser (no old cookies) on linkedin.com/login and waits up to 30 minutes
     for you to sign in to the new account; the session lands in data/linkedin_state.json,
     which every LinkedIn run reads (scan, Easy Apply, Premium, posts, phone queue, Simplify)
  2. checks the saved session really opens LinkedIn signed in
  3. puts linkedin.com back in data/platform_logins.json
  4. enables the scheduled tasks LinkedInPremium, LinkedInPostsWatch and LiveFeed and starts them
  5. rebuilds the Premium page so the phone lists LinkedInPremium again

Nothing is enabled when the sign-in does not complete.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import linkedin

ROOT = Path(__file__).resolve().parent.parent.parent
LOGINS = ROOT / "data" / "platform_logins.json"
TASKS = ["LinkedInPremium", "LinkedInPostsWatch", "LiveFeed"]


def verify() -> bool:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser, _ctx, _page = linkedin.open_session(p, headless=True)
        except linkedin.NotLoggedIn as exc:
            print(f"  Saved session does not open LinkedIn signed in: {exc}")
            return False
        browser.close()
    return True


def add_login_host() -> None:
    try:
        d = json.loads(LOGINS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {"hosts": []}
    hosts = set(d.get("hosts") or [])
    hosts.add("linkedin.com")
    d["hosts"] = sorted(hosts)
    d["updated"] = time.strftime("%Y-%m-%d %H:%M")
    LOGINS.write_text(json.dumps(d, indent=1), encoding="utf-8")


def enable_tasks() -> None:
    for t in TASKS:
        ps = (f"$t = Get-ScheduledTask -TaskName '{t}' -ErrorAction SilentlyContinue; "
              f"if ($t) {{ Enable-ScheduledTask -TaskName '{t}' | Out-Null; Start-ScheduledTask -TaskName '{t}'; 'on' }} else {{ 'missing' }}")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        print(f"  task {t}: {(r.stdout or r.stderr).strip() or 'no answer'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-login", action="store_true", dest="no_login", help="skip the sign-in, only resume")
    ap.add_argument("--minutes", type=int, default=30, help="how long to wait for the sign-in (default 30)")
    args = ap.parse_args(argv)

    if not args.no_login:
        print("Opening a clean browser: sign in to the NEW LinkedIn account there.")
        if not linkedin.login(timeout_sec=args.minutes * 60):
            print("No sign-in, so nothing was switched on. Run linkedin_resume.bat again when ready.")
            return 1
    if not verify():
        print("Nothing was switched on. Run linkedin_resume.bat again and finish the sign-in.")
        return 1
    print("LinkedIn session works. Switching the LinkedIn services back on:")
    add_login_host()
    print("  linkedin.com is back in data/platform_logins.json")
    enable_tasks()
    r = subprocess.run([sys.executable, "-m", "naukri.jobs.linkedin_premium", "--report"], cwd=str(ROOT))
    print(f"  phone Premium page rebuilt (exit {r.returncode})")
    print("Done. The next scan, apply pass, Premium pass and posts watch use the new account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
