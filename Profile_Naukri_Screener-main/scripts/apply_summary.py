"""Apply the profile summary alone, verifying the dialog before typing."""
import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

import yaml
from playwright.sync_api import sync_playwright
from naukri.session import open_profile
from naukri import selectors as S

NEW = yaml.safe_load(
    (_bootstrap.ROOT / "changes.yaml").read_text(encoding="utf-8")
)["profile_summary"].strip()

with sync_playwright() as p:
    browser, _c, page = open_profile(p, headless=False)
    try:
        for _ in range(8):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(500)

        trigger = page.locator(S.EDITORS["profile_summary"]["trigger"][0])
        print("trigger matches:", trigger.count())
        trigger.first.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        trigger.first.click()

        # Wait for THE textarea specifically. If the wrong dialog opened, this
        # raises before any key is pressed - which is the whole point.
        page.wait_for_selector("#profileSummaryTxt", state="visible", timeout=15000)
        box = page.locator("#profileSummaryTxt").first

        current = box.input_value()
        print("current value starts:", repr(current[:70]))
        assert "QA Automation Engineer" in current, "unexpected dialog contents - aborting"

        box.click()
        box.fill("")            # fill() sets value directly, no keystroke stream
        page.wait_for_timeout(300)
        box.fill(NEW)
        page.wait_for_timeout(500)

        wrote = box.input_value().strip()
        print("wrote length:", len(wrote))
        assert wrote == NEW, f"readback mismatch: {wrote[:80]!r}"

        page.locator("button.btn-dark-ot:visible", has_text="Save").first.click()
        page.wait_for_timeout(4000)
        print("saved")
    finally:
        browser.close()
