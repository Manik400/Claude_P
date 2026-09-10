"""Fix a Work Sample entry: correct the URL and fill the description.

Content comes from the `work_sample` section of scripts/profile_edits.yaml.

A public repository link a reviewer can open in ten seconds is worth more than
any description of one - but paste the browsable URL, not the clone URL. A
".git" suffix 404s for anyone who clicks it.
"""
import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

from playwright.sync_api import sync_playwright
from naukri.session import open_profile

SAMPLE = _bootstrap.edits("work_sample")
for _required in ("title", "url", "description"):
    if not SAMPLE.get(_required):
        raise SystemExit(
            f"\n  scripts/profile_edits.yaml: work_sample is missing "
            f"'{_required}'.\n")

# The existing entry is found by its exact on-profile title.
TRIGGER = (f"xpath=//*[normalize-space(text())='{SAMPLE['title'].strip()}']"
           "/following-sibling::*[contains(@class,'edit')][1]")
URL = SAMPLE["url"].strip()
DESC = SAMPLE["description"].strip()

if URL.endswith(".git"):
    raise SystemExit(
        "\n  work_sample.url ends in '.git' - that is the clone URL and it "
        "404s in a browser.\n  Use the repository page URL instead.\n")

with sync_playwright() as p:
    browser, _c, page = open_profile(p, headless=False)
    try:
        for _ in range(10):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)

        page.locator(TRIGGER).first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        page.locator(TRIGGER).first.click()
        page.wait_for_selector("#workSample-url_0", state="visible", timeout=15000)
        page.wait_for_timeout(1200)

        url = page.locator("#workSample-url_0").first
        desc = page.locator("#workSample-description_0").first
        print("url before:", repr(url.input_value()))
        assert url.input_value().endswith(".git"), "url does not end in .git - already fixed?"

        url.click(); url.fill(""); page.wait_for_timeout(250); url.fill(URL)
        page.wait_for_timeout(400)
        desc.click(); desc.fill(""); page.wait_for_timeout(250); desc.fill(DESC)
        page.wait_for_timeout(500)

        print("url after: ", repr(url.input_value()))
        print("desc len:  ", len(desc.input_value()))
        assert url.input_value().strip() == URL, "url did not take"
        assert desc.input_value().strip().startswith("Python test automation"), "desc did not take"

        save = page.locator("button.btn-dark-ot:visible").last
        print("save button:", repr(save.inner_text()))
        save.click()
        page.wait_for_timeout(4500)
        print("saved")
    finally:
        browser.close()
