"""Company-site postings: open them in a browser that has Simplify Copilot.

    python offsite_apply.py --setup                 open a window: log in to Simplify once
    python offsite_apply.py --try <url>             open one posting, let Simplify fill it, screenshot
    python offsite_apply.py --try <url> --submit    ...and press the form's Submit

Most postings the worldwide search finds are NOT one-click: Indeed, Seek,
company career pages, Greenhouse / Lever / Workday / Ashby forms. Filling
those by script is a losing fight (every ATS is different). Simplify Copilot
(https://simplify.jobs, Chrome extension pbanhockgagggenencehbnadejlgchfc)
already fills 500+ of them from a profile you complete once. So the queue
hands "web" items to a Chromium that has the extension loaded and your
Simplify login saved:

    1. open the posting; if the page has an Apply button, click it
    2. wait for the application form; Simplify's autofill runs on its own
       on supported sites (its banner appears at the top of the form)
    3. take a screenshot to data/apply/shots/<key>.png
    4. mode "simplify":         stop here -> status "prefilled" (finish it on the PC)
       mode "simplify-submit":  press the form's Submit -> "submitted" when a
                                thank-you page follows, "prefilled" when not

EXPERIMENTAL. Whether a given form ends up fully filled depends on Simplify,
not on this script; check the screenshot and the Track tab, and keep the
default "simplify" (no submit) until you have seen a few good screenshots.

Setup, once:
    * Install Simplify Copilot in Chrome and complete your Simplify profile.
    * python offsite_apply.py --setup   (finds the extension in Chrome's
      folder, opens a window with it: sign in to Simplify, close the window)
    * On the phone: Settings -> Company-site postings -> "Simplify fills, I submit".

Extensions need a persistent context and (for a hidden run) Chromium's new
headless mode; both are handled here.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from phone_publish import config_dir  # noqa: E402

EXT_ID = "pbanhockgagggenencehbnadejlgchfc"
PROFILE_DIR = os.path.join(config_dir(), "simplify-profile")
SHOTS_DIR = os.path.join(config_dir(), "shots")

APPLY_BUTTON = re.compile(r"^\s*(apply( now| for this job| to this job)?|easy apply|apply on company (web)?site|"
                          r"i'm interested|start application|apply for this position)\s*$", re.I)
SUBMIT_BUTTON = re.compile(r"^\s*(submit( application| your application)?|send application|apply|finish|"
                           r"submit and continue|complete application)\s*$", re.I)
THANKS = re.compile(r"thank you|application (has been )?(received|submitted|sent)|we('ve| have) received your application|"
                    r"successfully (applied|submitted)", re.I)


def extension_dir() -> str | None:
    """Simplify's unpacked folder: an explicit path, else Chrome's own copy."""
    env = os.environ.get("SIMPLIFY_EXTENSION_DIR")
    if env and os.path.isfile(os.path.join(env, "manifest.json")):
        return env
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    roots = [os.path.join(local, "Google", "Chrome", "User Data"),
             os.path.join(local, "Microsoft", "Edge", "User Data"),
             os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")]
    found = []
    for root in roots:
        found += glob.glob(os.path.join(root, "*", "Extensions", EXT_ID, "*", "manifest.json"))
    if not found:
        return None
    found.sort(key=os.path.getmtime)
    return os.path.dirname(found[-1])


def ready() -> bool:
    return bool(extension_dir()) and os.path.isdir(PROFILE_DIR)


def _launch(p, headed: bool):
    ext = extension_dir()
    if not ext:
        raise RuntimeError("Simplify Copilot is not installed in Chrome (or set SIMPLIFY_EXTENSION_DIR)")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    args = ["--disable-extensions-except=" + ext, "--load-extension=" + ext, "--no-first-run"]
    if not headed:
        args.append("--headless=new")
    return p.chromium.launch_persistent_context(
        PROFILE_DIR, headless=False, args=args, viewport={"width": 1280, "height": 900},
        channel=os.environ.get("SIMPLIFY_CHANNEL") or None)


def setup() -> int:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _launch(p, headed=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://simplify.jobs/auth/login")
        print("Sign in to Simplify in the window that opened, then close the window.")
        try:
            while ctx.pages:
                time.sleep(1)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    print("Saved. The queue can now hand company-site postings to Simplify.")
    return 0


def _click_first(page, pattern: re.Pattern, timeout_ms: int = 4000) -> bool:
    for frame in [page.main_frame] + page.frames:
        try:
            for el in frame.locator("button, a[role=button], a, input[type=submit]").all()[:120]:
                txt = (el.inner_text(timeout=300) if el.evaluate("e => e.tagName") != "INPUT" else el.get_attribute("value") or "")
                if pattern.match(txt or "") and el.is_visible():
                    el.click(timeout=timeout_ms)
                    return True
        except Exception:
            continue
    return False


def apply(url: str, submit: bool = False, dry_run: bool = False, headed: bool | None = None) -> tuple[str, str]:
    """Returns (status, note): prefilled | submitted | offsite-error | would-apply."""
    if headed is None:
        headed = not os.environ.get("NAUKRI_BACKGROUND")
    if not ready():
        return "offsite-error", "Simplify browser not set up: run site\\tools\\offsite_apply.py --setup on the PC"
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS_DIR, exist_ok=True)
    key = re.sub(r"[^a-z0-9]+", "-", url.lower())[:80]
    shot = os.path.join(SHOTS_DIR, key + ".png")
    with sync_playwright() as p:
        ctx = _launch(p, headed=headed)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            if _click_first(page, APPLY_BUTTON):
                page.wait_for_timeout(2500)
                if len(ctx.pages) > 1:          # the ATS opened in a new tab
                    page = ctx.pages[-1]
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
            # Simplify's autofill needs a moment; on supported sites it runs by itself.
            page.wait_for_timeout(9000)
            filled = page.evaluate(
                "() => Array.from(document.querySelectorAll('input,textarea,select')).filter(e => e.value && e.type !== 'hidden').length")
            page.screenshot(path=shot, full_page=False)
            if dry_run:
                return "would-apply", "%d field(s) filled; dry run" % filled
            if not submit:
                return "prefilled", "%d field(s) filled by Simplify; finish and submit on the PC (screenshot: %s)" % (filled, shot)
            if filled < 3:
                return "prefilled", "only %d field(s) filled - not submitting; finish on the PC (screenshot: %s)" % (filled, shot)
            if not _click_first(page, SUBMIT_BUTTON):
                return "prefilled", "%d field(s) filled; no Submit button found - finish on the PC (%s)" % (filled, shot)
            page.wait_for_timeout(5000)
            body = page.inner_text("body", timeout=5000) if page.locator("body").count() else ""
            page.screenshot(path=shot.replace(".png", "-after.png"), full_page=False)
            if THANKS.search(body or ""):
                return "submitted", "submitted via Simplify (%d fields)" % filled
            return "prefilled", "pressed Submit but saw no confirmation - check %s" % shot.replace(".png", "-after.png")
        except Exception as exc:
            return "offsite-error", str(exc)[:200]
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="open a window to sign in to Simplify once")
    ap.add_argument("--try", dest="url", help="open one posting and let Simplify fill it")
    ap.add_argument("--submit", action="store_true", help="with --try: press Submit")
    ap.add_argument("--hidden", action="store_true", help="with --try: run in the background")
    a = ap.parse_args(argv)
    if a.setup:
        return setup()
    if a.url:
        st, note = apply(a.url, submit=a.submit, headed=not a.hidden)
        print(st, "-", note)
        return 0
    ext = extension_dir()
    print("extension:", ext or "NOT FOUND (install Simplify Copilot in Chrome)")
    print("profile:  ", PROFILE_DIR, "(ready)" if os.path.isdir(PROFILE_DIR) else "(run --setup)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
