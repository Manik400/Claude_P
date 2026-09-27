"""Set the total-experience header. Naukri does not derive it from employment.

Recruiter search filters on this field, not on the sum of the employment
entries - so adding past roles does nothing for visibility until this is
updated to match them.

Usage: python set_total_experience.py "1 Year" "11 Months"
"""
import sys

import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

from playwright.sync_api import sync_playwright
from naukri.session import open_profile

# No default: this writes to your live profile, and a stale default would
# quietly overwrite your real experience with someone else's.
if len(sys.argv) < 3:
    sys.exit('Usage: python set_total_experience.py "1 Year" "11 Months"')
YEARS, MONTHS = sys.argv[1], sys.argv[2]

with sync_playwright() as p:
    browser, _c, page = open_profile(p, headless=False)
    try:
        page.wait_for_timeout(2500)
        page.locator(".hdn em.icon.edit").first.click()
        page.wait_for_selector("#exp-years-droopeFor", state="visible", timeout=15000)
        page.wait_for_timeout(1500)

        years = page.locator("#exp-years-droopeFor").first
        months = page.locator("#exp-months-droopeFor").first
        print("before:", years.input_value(), "/", months.input_value())

        for droope, want in (("exp-years-droope", YEARS), ("exp-months-droope", MONTHS)):
            page.locator(f"#{droope}For").first.click()
            page.wait_for_timeout(1200)
            page.locator(f"#ul_{droope} li.pickVal a", has_text=want).first.click()
            page.wait_for_timeout(1000)

        print("after: ", years.input_value(), "/", months.input_value())
        assert years.input_value().strip() == YEARS, "years did not take"
        assert months.input_value().strip() == MONTHS, "months did not take"

        page.locator("#saveBasicDetailsBtn").click()
        page.wait_for_timeout(4500)
        still_open = page.locator("#exp-years-droopeFor").count() and \
            page.locator("#exp-years-droopeFor").first.is_visible()
        print("dialog still open:", bool(still_open))
    finally:
        browser.close()
