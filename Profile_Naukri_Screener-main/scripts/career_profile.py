"""Set the Career Profile block: the role you want, and your expected salary.

Both come from the `career_profile` section of scripts/profile_edits.yaml, and
both are recruiter search filters - the role decides which searches you appear
in at all, and the salary decides whether a recruiter opens your profile after
finding it.

`expect_current_role` in that file is an optional safety check: the script
refuses to run unless your profile currently shows that role. Naukri's edit
icons are near-identical between sections, so a mis-click otherwise overwrites
whichever dialog happened to open.
"""
import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

from playwright.sync_api import sync_playwright
from naukri.session import open_profile

_CAREER = _bootstrap.edits("career_profile")
ROLE = str(_CAREER.get("role") or "").strip()
SALARY = str(_CAREER.get("expected_salary") or "").strip()
EXPECT_CURRENT = str(_CAREER.get("expect_current_role") or "").strip()

if not ROLE or not SALARY:
    raise SystemExit(
        "  scripts/profile_edits.yaml: career_profile needs both 'role' and "
        "'expected_salary'.")

XP = ("xpath=//*[normalize-space(text())='Career profile']"
      "/following-sibling::span[contains(@class,'edit')][1]")

with sync_playwright() as p:
    browser, _c, page = open_profile(p, headless=False)
    try:
        for _ in range(10):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)

        page.locator(XP).first.click()
        page.wait_for_selector("#roleDroopeFor", state="visible", timeout=15000)
        page.wait_for_timeout(1500)

        role_box = page.locator("#roleDroopeFor").first
        print("role before:", repr(role_box.input_value()))
        if EXPECT_CURRENT and role_box.input_value().strip() != EXPECT_CURRENT:
            raise SystemExit(
                f"  profile shows role {role_box.input_value().strip()!r}, but "
                f"profile_edits.yaml expects {EXPECT_CURRENT!r}. "
                f"Nothing changed. Update expect_current_role, or remove it to "
                f"skip this check.")

        role_box.click()
        page.wait_for_timeout(1500)
        option = page.locator("#ul_roleDroope li.pickVal a", has_text=ROLE).first
        print("option matches:", page.locator("#ul_roleDroope li.pickVal a", has_text=ROLE).count())
        option.click()
        page.wait_for_timeout(1500)
        print("role after: ", repr(role_box.input_value()))

        sal = page.locator(".salary-field-container .currency-input").first
        print("salary before:", repr(sal.input_value()))
        sal.click()
        sal.fill("")
        page.wait_for_timeout(300)
        sal.fill(SALARY)
        page.wait_for_timeout(600)
        print("salary after: ", repr(sal.input_value()))

        assert role_box.input_value().strip() == ROLE, "role did not take"
        assert SALARY in sal.input_value(), "salary did not take"

        save = page.locator("button.btn-dark-ot:visible").last
        print("save button:", repr(save.inner_text()))
        save.click()
        page.wait_for_timeout(4500)
        print("saved")
    finally:
        browser.close()
