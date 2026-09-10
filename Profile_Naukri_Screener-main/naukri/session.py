"""Log in once by hand, reuse that session forever after.

The password never touches this codebase. `login()` opens a real browser,
parks on Naukri's login page and waits for *you* to sign in - which means
OTP, captcha and device-verification all just work, because a human is
there for them. The resulting cookies are written to data/state.json and
every later run loads that file instead of logging in again.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from . import selectors as S

log = logging.getLogger("naukri.session")

DEFAULT_STATE = Path(__file__).resolve().parent.parent / "data" / "state.json"


class NotLoggedIn(RuntimeError):
    """Raised when no usable saved session exists."""


def launch_browser(p, headless: bool):
    """Launch the installed Chrome, falling back to Playwright's bundled Chromium.

    The bundled Chromium fails on some Windows machines with "side-by-side
    configuration is incorrect". Set NAUKRI_BROWSER_CHANNEL to "msedge" to use
    Edge, or to "none" to force the bundled build.
    """
    channel = os.environ.get("NAUKRI_BROWSER_CHANNEL", "chrome")
    if channel and channel.lower() != "none":
        try:
            return p.chromium.launch(headless=headless, channel=channel)
        except Exception as exc:
            log.warning("Could not launch %s (%s) - using bundled Chromium", channel, exc)
    return p.chromium.launch(headless=headless)


def is_logged_in(page) -> bool:
    """Best-effort check that the current page belongs to a signed-in user."""
    url = page.url or ""

    # Naukri sits behind Akamai, which serves an "Access Denied" body while
    # leaving the requested URL in the address bar. Without this check the URL
    # marker below matches and we report a healthy session for a blocked page.
    try:
        if "Access Denied" in page.locator("body").inner_text(timeout=3000)[:400]:
            log.warning("Blocked by Akamai bot protection - run with a visible browser")
            return False
    except Exception:
        pass

    if any(marker in url for marker in S.LOGGED_IN_URL_MARKERS):
        return True
    if "nlogin/login" in url:
        return False
    for selector in S.LOGGED_IN_MARKERS:
        try:
            if page.locator(selector).first.is_visible(timeout=1500):
                return True
        except Exception:
            continue
    return False


def _chrome_path() -> str | None:
    """Path to an installed Google Chrome, or None."""
    candidates = [os.environ.get("NAUKRI_CHROME_PATH")]
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    return next((c for c in candidates if c and os.path.exists(c)), None)


def login(state_path: Path = DEFAULT_STATE, timeout_sec: int = 300) -> bool:
    """Open a browser, wait for a manual login, save the session.

    Returns True once cookies are captured, False on timeout.

    Prefers a plain Chrome window with nothing attached during sign-in:
    Google refuses "Sign in with Google" in any automation-controlled browser
    ("This browser or app may not be secure"). Playwright attaches only after
    Naukri shows a logged-in page, just long enough to copy the cookies.
    """
    chrome = _chrome_path()
    if chrome:
        return _login_real_chrome(chrome, state_path, timeout_sec)
    return _login_playwright(state_path, timeout_sec)


def _login_real_chrome(chrome: str, state_path: Path, timeout_sec: int, port: int = 9333) -> bool:
    import subprocess
    import urllib.request

    from playwright.sync_api import sync_playwright

    def open_tabs():
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as resp:
            return json.loads(resp.read())

    state_path.parent.mkdir(parents=True, exist_ok=True)
    # A dedicated profile, gitignored under data/. Chrome refuses remote
    # debugging on your everyday profile, and this keeps the two apart.
    profile_dir = state_path.parent / "chrome-login-profile"
    proc = subprocess.Popen([
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        S.LOGIN_URL,
    ])

    print("\n  A Chrome window is open. Sign in to Naukri there.")
    print("  Email/password, OTP and 'Sign in with Google' all work.")
    print(f"  Waiting up to {timeout_sec // 60} minutes...\n")

    deadline = time.time() + timeout_sec
    try:
        while time.time() < deadline:
            try:
                tabs = open_tabs()
            except Exception:
                if proc.poll() is not None and time.time() > deadline - timeout_sec + 10:
                    print("  The browser was closed before the login finished.")
                    return False
                time.sleep(1)
                continue
            if any(t.get("type") == "page" and any(m in t.get("url", "") for m in S.LOGGED_IN_URL_MARKERS)
                   for t in tabs):
                time.sleep(3)  # let the post-login redirects settle
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                    browser.contexts[0].storage_state(path=str(state_path))
                log.info("Session saved to %s", state_path)
                print(f"  Login captured. Session saved to {state_path}")
                return True
            time.sleep(1)
        print("  Timed out waiting for login.")
        return False
    finally:
        if proc.poll() is None:
            proc.terminate()


def _login_playwright(state_path: Path, timeout_sec: int) -> bool:
    """Fallback when Chrome is not installed. Google sign-in will not work here."""
    from playwright.sync_api import sync_playwright

    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Headed on purpose - a human is completing this flow.
        browser = launch_browser(p, headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(S.LOGIN_URL, wait_until="domcontentloaded")

        print("\n  A browser window is open. Sign in to Naukri there.")
        print("  Complete any OTP or captcha as normal - just finish the login.")
        print(f"  Waiting up to {timeout_sec // 60} minutes...\n")

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if is_logged_in(page):
                # Let the post-login redirects settle before snapshotting cookies.
                page.wait_for_timeout(3000)
                context.storage_state(path=str(state_path))
                log.info("Session saved to %s", state_path)
                print(f"  Login captured. Session saved to {state_path}")
                browser.close()
                return True
            page.wait_for_timeout(1000)

        print("  Timed out waiting for login.")
        browser.close()
        return False


def open_profile(p, state_path: Path = DEFAULT_STATE, headless: bool = True):
    """Return (browser, context, page) sitting on the profile page.

    Raises NotLoggedIn if the saved session is missing or has expired, so
    callers can tell the user to re-run `--login` instead of failing on a
    confusing selector timeout further down.
    """
    if not state_path.exists():
        raise NotLoggedIn(f"No saved session at {state_path}. Run: python main.py --login")

    try:
        json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise NotLoggedIn(f"Session file at {state_path} is unreadable ({exc}). Re-run --login.")

    browser = launch_browser(p, headless=headless)
    context = browser.new_context(
        storage_state=str(state_path),
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page.goto(S.PROFILE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)  # profile widgets lazy-load after first paint

    if not is_logged_in(page):
        browser.close()
        raise NotLoggedIn("Saved session has expired. Run: python main.py --login")

    return browser, context, page
