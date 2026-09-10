"""Clear the doorstep-level address details from Personal details.

Deliberately untouched:
  - Category: no "prefer not to say" option exists, and a radio group cannot be
    un-selected. Switching to "Other" would be a false statement.
  - Date of birth: part of Naukri's identity data, not worth fighting the form.
  - "Single parent" diversity flag: a self-declaration. It looks like a mis-click
    next to Married, but only its owner can say that.
  - Hometown: kept, since it carries a genuine relocation signal for recruiters.
"""
import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

from playwright.sync_api import sync_playwright
from naukri.session import open_profile

TRIGGER = ("xpath=//*[normalize-space(text())='Personal details']"
           "/following-sibling::*[contains(@class,'edit')][1]")
CLEAR = ["pd-permanent-address", "pd-pincode"]

with sync_playwright() as p:
    browser, _c, page = open_profile(p, headless=False)
    try:
        for _ in range(10):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)
        page.locator(TRIGGER).first.click()
        page.wait_for_selector("#pd-permanent-address", state="visible", timeout=15000)
        page.wait_for_timeout(1500)

        for field_id in CLEAR:
            box = page.locator(f"#{field_id}").first
            print(f"{field_id} before: {box.input_value()!r}")
            box.click()
            box.fill("")
            page.wait_for_timeout(400)
            print(f"{field_id} after:  {box.input_value()!r}")
            assert box.input_value() == "", f"{field_id} did not clear"

        print("hometown kept:", repr(page.locator("#pd-hometown").first.input_value()))

        save = page.locator("button.btn-dark-ot:visible").last
        print("save button:", repr(save.inner_text()))
        save.click()
        page.wait_for_timeout(4500)
        print("saved")
    finally:
        browser.close()
