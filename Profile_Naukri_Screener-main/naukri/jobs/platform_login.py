"""Sign in to the job platforms once, in the browser auto-apply uses.

    python main.py --platform-login            every platform
    python main.py --platform-login seek xing  just these

Opens the automation browser (the Simplify profile, %LOCALAPPDATA%\\JobHuntPhone\\
simplify-profile) with one tab per platform. You sign in on each tab yourself -
this never types a password or creates an account. The browser profile keeps
the sessions, so later runs apply through those platforms instead of stopping
at "needs its own account".

When you are done, press Enter here and say which ones you signed in to; they
are saved to data/platform_logins.json (career_apply.saved_logins reads it).
Run it again whenever a platform logs you out.
"""
from __future__ import annotations

import json
import time

from .career_apply import LOGINS_FILE, saved_logins

# name, where to sign in, the host substring auto-apply checks
PLATFORMS = [
    ("LinkedIn", "https://www.linkedin.com/login", "linkedin.com"),
    ("Naukri", "https://www.naukri.com/nlogin/login", "naukri.com"),
    ("Instahyre", "https://www.instahyre.com/login/", "instahyre.com"),
    ("Hirist", "https://www.hirist.tech/", "hirist."),
    ("Cutshort", "https://cutshort.io/", "cutshort.io"),
    ("foundit", "https://www.foundit.in/", "foundit.in"),
    ("Wellfound", "https://wellfound.com/login", "wellfound.com"),
    ("Relocate.me", "https://relocate.me/", "relocate.me"),
    ("Indeed", "https://secure.indeed.com/account/login", "indeed."),
    ("StepStone", "https://www.stepstone.de/", "stepstone."),
    ("XING", "https://login.xing.com/", "xing.com"),
    ("SEEK", "https://www.seek.com.au/", "seek.com"),
    ("JobsDB", "https://th.jobsdb.com/", "jobsdb.com"),
    ("Daijob", "https://www.daijob.com/en/", "daijob.com"),
]


def save(names: list[str]) -> list[str]:
    """Record platforms (by name, e.g. "linkedin seek") as signed in, without opening anything."""
    chosen = [p for p in PLATFORMS if any(n.lower() in p[0].lower() for n in names)] if names != ["all"] else PLATFORMS
    hosts = sorted(saved_logins() | {p[2] for p in chosen})
    LOGINS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOGINS_FILE.write_text(json.dumps({"hosts": hosts, "updated": time.strftime("%Y-%m-%d %H:%M")}, indent=1),
                           encoding="utf-8")
    return [p[0] for p in chosen]


def run(only: list[str] | None = None, prompt: bool = True) -> int:
    """prompt=False: open the tabs, wait for the automation browser to be free first (a scan may
    be using it), and return when you close the window; record the logins afterwards with save()."""
    from playwright.sync_api import sync_playwright

    from . import simplify

    import os
    os.environ["NAUKRI_SHOW"] = "1"            # this one needs a window: you sign in by hand
    os.environ.pop("NAUKRI_BACKGROUND", None)
    if not prompt:
        simplify.PROFILE_BUSY_WAIT_S = 3600    # a running scan holds the profile; wait for it
    if not prompt:
        wanted = [p for p in PLATFORMS if not only or any(o.lower() in p[0].lower() for o in only)]
        with sync_playwright() as pw:
            browser = simplify.launch(pw, headless=False, offscreen=False)
            ctx = browser.context
            for name, url, _host in wanted:
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as exc:
                    print(f"  {name}: could not open {url} ({str(exc)[:60]})")
            print(f"LOGIN BROWSER OPEN at {time.strftime('%H:%M')}: {len(wanted)} tabs. Sign in, then close the window.", flush=True)
            while True:                        # until you close the window
                try:
                    if not ctx.pages:
                        break
                    ctx.pages[0].wait_for_timeout(2000)
                except Exception:
                    break
            try:
                browser.close()
            except Exception:
                pass
        print(f"LOGIN BROWSER CLOSED at {time.strftime('%H:%M')}", flush=True)
        return 0
    wanted = [p for p in PLATFORMS if not only or any(o.lower() in p[0].lower() for o in only)]
    if not wanted:
        print("No platform matches: " + ", ".join(only or []))
        return 1
    have = saved_logins()
    with sync_playwright() as pw:
        browser = simplify.launch(pw, headless=False, offscreen=False)
        ctx = browser.context
        for name, url, _host in wanted:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:  # a slow site still gets its tab
                print(f"  {name}: could not open {url} ({str(exc)[:60]})")
            time.sleep(0.4)
        print("\nA browser opened with one tab per platform:")
        for i, (name, _url, host) in enumerate(wanted, 1):
            print(f"  {i:2d}. {name}{'   (saved before)' if host in have else ''}")
        print("\nSign in on each tab yourself (use 'Continue with Google' where you like).")
        print("Leave the browser open, come back here and press Enter when you are done.")
        try:
            input()
            picked = input("Which did you sign in to? Numbers separated by spaces, 'all', or Enter for none: ").strip().lower()
        finally:
            browser.close()
    if picked == "all":
        chosen = wanted
    else:
        idx = {int(x) for x in picked.replace(",", " ").split() if x.isdigit()}
        chosen = [p for i, p in enumerate(wanted, 1) if i in idx]
    hosts = sorted(have | {p[2] for p in chosen})
    LOGINS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOGINS_FILE.write_text(json.dumps({"hosts": hosts, "updated": time.strftime("%Y-%m-%d %H:%M")}, indent=1),
                           encoding="utf-8")
    print(f"Saved: {', '.join(p[0] for p in chosen) or 'nothing new'}. Auto-apply now applies through: {', '.join(hosts) or 'none'}")
    return 0
