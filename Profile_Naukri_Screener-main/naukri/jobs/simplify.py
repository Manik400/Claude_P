"""One browser for every application: Chromium with Simplify Copilot loaded.

Simplify Copilot (https://simplify.jobs, Chrome extension
pbanhockgagggenencehbnadejlgchfc) fills 500+ application forms - Greenhouse,
Lever, Workday, Ashby, SmartRecruiters, company career pages - from a profile
you complete once on simplify.jobs. Filling those by script is a losing fight
(every ATS is different), so when `simplify: true` is set in jobs.yaml the
career applier runs INSIDE a browser that has the extension, and the order on
every form becomes:

    1. open the posting on Naukri / LinkedIn / the board it came from, with
       your saved logins (the cookies from data/state.json and
       data/linkedin_state.json are loaded into this browser)
    2. press the board's Apply button and follow it to the company's form -
       Naukri "Apply on company site", LinkedIn's plain Apply (Easy Apply
       stays with the Easy Apply walker), or the posting's own Apply
    3. stop at a wall: sign-in / create-account / password box / CAPTCHA
       -> "login-required" or "captcha", nothing typed, the job is left for you
    4. let Simplify fill the form (its autofill runs by itself on the sites
       it knows; the floating "Autofill" button is pressed when it shows)
    5. career_apply.fill_form() answers what Simplify left empty - screening
       questions from your answer bank, the resume upload, consent boxes
    6. Submit, follow the form's pages, look for the thank-you page

What the extension does NOT need: any API. It works on the page like it does
in your own Chrome. What it does need is a persistent browser profile with
your Simplify login in it, made once:

    python -m naukri.jobs.simplify --setup      sign in to Simplify in the
                                               window that opens, close it
    python -m naukri.jobs.simplify              show what is set up
    python -m naukri.jobs.simplify --try URL [--submit]   one posting, by hand

The profile lives in %LOCALAPPDATA%\\JobHuntPhone\\simplify-profile (the phone
site's own folder, so site/tools/offsite_apply.py and this module share it);
SIMPLIFY_PROFILE_DIR overrides that, SIMPLIFY_EXTENSION_DIR points at an
unpacked copy of the extension when Chrome's own copy is not found.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("naukri.jobs.simplify")

EXT_ID = "pbanhockgagggenencehbnadejlgchfc"


def _config_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JobHuntPhone")


PROFILE_DIR = os.environ.get("SIMPLIFY_PROFILE_DIR") or os.path.join(_config_dir(), "simplify-profile")

# Simplify's own floating widget: the button that (re)runs its autofill.
AUTOFILL_TEXT = re.compile(r"^\s*(autofill|auto-fill|fill (this )?(form|application)|autofill with simplify)\s*$", re.I)



def extension_dir() -> str | None:
    """Simplify's unpacked folder: an explicit path, else Chrome's own copy."""
    env = os.environ.get("SIMPLIFY_EXTENSION_DIR")
    if env and os.path.isfile(os.path.join(env, "manifest.json")):
        return env
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    roots = [os.path.join(local, "Google", "Chrome", "User Data"),
             os.path.join(local, "Microsoft", "Edge", "User Data"),
             os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")]
    found: list[str] = []
    for root in roots:
        found += glob.glob(os.path.join(root, "*", "Extensions", EXT_ID, "*", "manifest.json"))
    if not found:
        return None
    found.sort(key=os.path.getmtime)
    return os.path.dirname(found[-1])


def wanted(config: dict) -> bool:
    """jobs.yaml `simplify: true`, or SIMPLIFY=1 in the environment."""
    if os.environ.get("SIMPLIFY", "").strip() in ("1", "true", "yes"):
        return True
    return bool(config.get("simplify"))


def ready() -> bool:
    return bool(extension_dir()) and os.path.isdir(PROFILE_DIR)


def why_not_ready() -> str:
    if not extension_dir():
        return ("Simplify Copilot is not installed in Chrome (or set SIMPLIFY_EXTENSION_DIR "
                "to an unpacked copy)")
    if not os.path.isdir(PROFILE_DIR):
        return "run once:  python -m naukri.jobs.simplify --setup   (sign in to Simplify)"
    return ""


# ------------------------------------------------------------------- browser

class SimplifyBrowser:
    """A persistent Chromium context with the extension; `.close()` like a Browser."""

    def __init__(self, context, headless: bool):
        self.context = context
        self._naukri_headless = headless

    def new_context(self, **_kw):
        return self.context

    def close(self) -> None:
        try:
            self.context.close()
        except Exception:
            pass


def _cookies_from(state_path: Path) -> list[dict]:
    """The cookies of a Playwright storage_state file, as add_cookies wants them."""
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for c in state.get("cookies") or []:
        cookie = {k: c[k] for k in ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite") if k in c}
        if cookie.get("sameSite") not in ("Strict", "Lax", "None"):
            cookie.pop("sameSite", None)
        if cookie.get("expires") in (None, -1):
            cookie.pop("expires", None)
        out.append(cookie)
    return out


def launch(p, headless: bool, states: list[Path] | None = None) -> SimplifyBrowser:
    """Chromium with Simplify loaded, plus the boards' saved logins.

    Extensions need a persistent context; in the background the new headless
    mode carries them. The Naukri / LinkedIn cookies are added on every
    launch, so a session refreshed by --login is picked up next run.
    """
    ext = extension_dir()
    if not ext:
        raise RuntimeError(why_not_ready())
    os.makedirs(PROFILE_DIR, exist_ok=True)
    args = ["--disable-extensions-except=" + ext, "--load-extension=" + ext, "--no-first-run",
            "--disable-features=CalculateNativeWinOcclusion"]
    if headless:
        args.append("--headless=new")
    context = p.chromium.launch_persistent_context(
        PROFILE_DIR, headless=False, args=args, viewport={"width": 1366, "height": 900},
        channel=os.environ.get("SIMPLIFY_CHANNEL") or None)
    cookies: list[dict] = []
    for state in states or []:
        if state and Path(state).exists():
            cookies += _cookies_from(Path(state))
    if cookies:
        try:
            context.add_cookies(cookies)
        except Exception as exc:  # a malformed cookie must not cost the run
            log.warning("Simplify browser: could not load saved logins (%s)", exc)
    # The extension opens its own welcome tab on launch; _follow_click() takes
    # the newest tab as "where the Apply button led", so that tab goes first.
    try:
        context.pages and context.pages[0].wait_for_timeout(1500)
        for extra in list(context.pages):
            if (extra.url or "").startswith("chrome-extension://"):
                extra.close()
    except Exception:
        pass
    return SimplifyBrowser(context, headless)


def _states() -> list[Path]:
    from ..session import DEFAULT_STATE
    from .linkedin import STATE_PATH as LINKEDIN_STATE
    return [DEFAULT_STATE, LINKEDIN_STATE]


def open_naukri(p, headless: bool):
    """(browser, context, page) on the Naukri profile page, in the Simplify browser.

    The same contract as session.open_profile(): NotLoggedIn when the saved
    session has expired, so the caller says "run --login" instead of failing
    on a selector further down.
    """
    from .. import selectors as S
    from ..session import NotLoggedIn, is_logged_in

    browser = launch(p, headless=headless, states=_states())
    page = browser.context.new_page()
    page.goto(S.PROFILE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    if not is_logged_in(page):
        browser.close()
        raise NotLoggedIn("Saved Naukri session has expired. Run: python main.py --login")
    return browser, browser.context, page


def open_linkedin(p, headless: bool):
    """(browser, context, page) on a signed-in LinkedIn, in the Simplify browser."""
    from . import linkedin as linkedin_mod

    browser = launch(p, headless=headless, states=_states())
    page = browser.context.new_page()
    page.goto(linkedin_mod.JOBS_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    if not linkedin_mod.is_logged_in(page, strict=True):
        browser.close()
        raise linkedin_mod.NotLoggedIn("Saved LinkedIn session has expired. Run: python main.py --linkedin-login")
    return browser, browser.context, page


def setup() -> int:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = launch(p, headless=False)
        ctx = browser.context
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://simplify.jobs/auth/login")
        print("Sign in to Simplify in the window that opened (manikgoyal400@gmail.com), then close the window.")
        try:
            while ctx.pages:
                time.sleep(1)
        except Exception:
            pass
        browser.close()
    print("Saved. Set `simplify: true` in jobs.yaml and every company-site form goes through Simplify.")
    return 0


# ------------------------------------------------------------------ autofill

_FILLED_JS = ("() => Array.from(document.querySelectorAll('input,textarea,select'))"
              ".filter(e => e.value && e.type !== 'hidden' && e.type !== 'submit' && e.type !== 'button').length")


def _filled(page) -> int:
    total = 0
    for frame in [page.main_frame] + [f for f in page.frames if f is not page.main_frame]:
        try:
            total += int(frame.evaluate(_FILLED_JS))
        except Exception:
            continue
    return total


def _press_autofill(page) -> bool:
    for frame in [page.main_frame] + [f for f in page.frames if f is not page.main_frame]:
        try:
            for el in frame.locator("button, [role=button], a").all()[:150]:
                txt = (el.inner_text(timeout=200) or "").strip()
                if AUTOFILL_TEXT.match(txt) and el.is_visible():
                    el.click(timeout=3000)
                    return True
        except Exception:
            continue
    return False


def autofill(page, wait_s: float = 14.0) -> int:
    """Give Simplify its turn on the form. Returns how many fields hold a value after.

    Simplify fills supported sites by itself a moment after the form appears;
    where it only offers its button, that is pressed. The wait ends early when
    the filled count has been still for a few seconds.
    """
    before = _filled(page)
    page.wait_for_timeout(3000)
    pressed = _press_autofill(page)
    last, still, deadline = _filled(page), 0.0, time.monotonic() + wait_s
    while time.monotonic() < deadline:
        page.wait_for_timeout(1000)
        now = _filled(page)
        if now == last:
            still += 1
            if still >= 3 and (now > before or not pressed):
                break
        else:
            last, still = now, 0.0
    after = _filled(page)
    log.info("Simplify: %d field(s) filled%s", max(0, after - before), " (Autofill pressed)" if pressed else "")
    return after



# --------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="open a window to sign in to Simplify once")
    ap.add_argument("--try", dest="url", help="apply to one posting through Simplify (fill only)")
    ap.add_argument("--submit", action="store_true", help="with --try: really submit")
    ap.add_argument("--hidden", action="store_true", help="with --try: run in the background")
    a = ap.parse_args(argv)
    if a.setup:
        return setup()
    if a.url:
        from playwright.sync_api import sync_playwright

        from . import answers as answers_mod, career_apply, config as config_mod, questions
        from ..session import DEFAULT_STATE
        from .linkedin import STATE_PATH as LINKEDIN_STATE

        if not ready():
            print(why_not_ready())
            return 1
        profile = config_mod.load_profile()
        config = config_mod.load(profile=profile)
        facts = answers_mod.build_facts(profile, config)
        facts["_bank"] = questions.load_bank()
        who = career_apply.applicant(profile, config)
        with sync_playwright() as p:
            browser = launch(p, headless=a.hidden, states=[DEFAULT_STATE, LINKEDIN_STATE])
            page = browser.context.new_page()
            page.goto(a.url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            print(career_apply.apply_from_page(page, {"url": a.url}, who, facts, dry_run=not a.submit,
                                               prefill=autofill))
            browser.close()
        return 0
    print("extension:", extension_dir() or "NOT FOUND (install Simplify Copilot in Chrome)")
    print("profile:  ", PROFILE_DIR, "(ready)" if os.path.isdir(PROFILE_DIR) else "(run --setup)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
