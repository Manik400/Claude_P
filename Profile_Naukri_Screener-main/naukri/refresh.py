"""The daily nudge: keep the profile at the top of recruiter searches.

Naukri's recruiter search ranks heavily on when a profile was last modified,
so a profile that is never touched sinks below identical ones edited today.
This makes the smallest possible edit - toggling a trailing full stop on the
resume headline - which bumps the modified timestamp without changing what a
human reads.

Run it once a day. Running it more often gains nothing and only makes the
traffic look automated.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from . import selectors as S
from .session import DEFAULT_STATE, open_profile
from .apply import _click_first, _fill_first

log = logging.getLogger("naukri.refresh")

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "data" / "refresh_log.json"


def _toggle_trailing_period(text: str) -> str:
    """Flip a trailing '.' on or off - a real change, invisible in practice."""
    text = text.rstrip()
    return text[:-1] if text.endswith(".") else text + "."


def refresh(state_path: Path = DEFAULT_STATE, headless: bool = True) -> bool:
    """Bump the profile's last-modified timestamp. Returns True on success."""
    from playwright.sync_api import sync_playwright

    editor = S.EDITORS["resume_headline"]

    with sync_playwright() as p:
        browser, _context, page = open_profile(p, state_path, headless=headless)
        try:
            _click_first(page, editor["trigger"], "resume headline edit button")
            page.wait_for_timeout(1500)

            current = None
            for selector in editor["input"]:
                locator = page.locator(selector).first
                if locator.count():
                    current = locator.input_value(timeout=5000)
                    break
            if not current:
                raise RuntimeError("Could not read the current resume headline.")

            new_text = _toggle_trailing_period(current)
            _fill_first(page, editor["input"], new_text, "resume headline input")
            page.wait_for_timeout(500)
            _click_first(page, editor["save"], "resume headline save button")
            page.wait_for_timeout(3000)

            _record(True, new_text)
            log.info("Profile refreshed")
            return True
        except Exception as exc:
            log.warning("Refresh failed: %s", exc)
            _record(False, str(exc))
            return False
        finally:
            browser.close()


def _record(ok: bool, detail: str) -> None:
    """Append the outcome so a silently-broken scheduled job is visible."""
    entries = []
    if LOG_FILE.exists():
        try:
            entries = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    entries.append({"at": datetime.now().isoformat(timespec="seconds"), "ok": ok, "detail": detail})
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(entries[-90:], indent=2), encoding="utf-8")
