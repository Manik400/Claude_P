"""Add an entry to the Projects section of your Naukri profile.

Content comes from the `project` section of scripts/profile_edits.yaml. The
project text is indexed by recruiter search, so name your technologies
explicitly there rather than describing them.
"""
import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

from playwright.sync_api import sync_playwright
from naukri.session import open_profile

PROJECT = _bootstrap.edits("project")
for _required in ("title", "employment", "client", "details"):
    if not PROJECT.get(_required):
        raise SystemExit(
            f"\n  scripts/profile_edits.yaml: project is missing "
            f"'{_required}'.\n")

TITLE = PROJECT["title"].strip()
DETAILS = PROJECT["details"].strip()
# Which employment entry the project hangs off. Matched as a substring against
# the dropdown, so a distinctive fragment of the company name is enough.
EMPLOYMENT = PROJECT["employment"].strip()
CLIENT = PROJECT["client"].strip()
# Optional: when the project started. Naukri wants both, and defaults here beat
# a Playwright timeout on a dropdown that never got a value.
START_YEAR = str(PROJECT.get("start_year") or "").strip()
START_MONTH = str(PROJECT.get("start_month") or "").strip()


def pick(page, droope: str, want: str) -> str:
    """Open a droope dropdown and click the option containing `want`."""
    page.locator(f"#{droope}For").first.click()
    page.wait_for_timeout(1200)
    opts = page.locator(f"#ul_{droope} li.pickVal a", has_text=want)
    print(f"  {droope}: {opts.count()} match(es) for {want!r}")
    opts.first.click()
    page.wait_for_timeout(1000)
    return page.locator(f"#{droope}For").first.input_value()


with sync_playwright() as p:
    browser, _c, page = open_profile(p, headless=False)
    try:
        for _ in range(10):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)

        page.locator("xpath=//*[normalize-space(text())='Add project']").first.click()
        page.wait_for_selector("#projectTitle", state="visible", timeout=15000)
        page.wait_for_timeout(1200)

        page.locator("#projectTitle").first.fill(TITLE)
        print("title:", repr(page.locator("#projectTitle").first.input_value()))

        print("tag to employment:", repr(pick(page, "eduExpId", EMPLOYMENT)))

        # Client is mandatory. Where the product is your employer's own, the
        # employer is the client. The suggestor may or may not offer a dropdown
        # entry, so accept free text when no exact suggestion comes back.
        client = page.locator("#clientName").first
        client.click()
        client.fill("")
        client.type(CLIENT, delay=40)
        page.wait_for_timeout(2000)
        sugg = page.locator("#sugDrp_clientName li.sugTouple")
        # The list can exist in the DOM while hidden - clicking it then blocks
        # forever. Only click a suggestion that is actually on screen.
        if sugg.count() and sugg.first.is_visible():
            print("clicking client suggestion")
            sugg.first.click()
            page.wait_for_timeout(800)
        else:
            print("no visible suggestion, keeping free text")
        print("client:", repr(client.input_value()))

        # Material-style radio: the <input> is visually hidden and unclickable,
        # so the label is the real hit target.
        page.locator("label[for='inprogress']").first.click()
        page.wait_for_timeout(800)
        print("in progress checked:", page.locator("#inprogress").first.is_checked())

        if START_YEAR:
            print("start year: ", repr(pick(page, "projStartYear", START_YEAR)))
        if START_MONTH:
            print("start month:", repr(pick(page, "projStartMonth", START_MONTH)))

        page.locator("#projectDetails").first.fill(DETAILS)
        page.wait_for_timeout(500)
        print("details len:", len(page.locator("#projectDetails").first.input_value()))

        print("details maxlength:", page.locator("#projectDetails").first.get_attribute("maxlength"))
        print("title maxlength:  ", page.locator("#projectTitle").first.get_attribute("maxlength"))

        page.locator("#submitProject").click()
        page.wait_for_timeout(5000)

        print("dialog text after save:")
        body = page.locator("#projectTitle").first
        if body.count():
            container = page.evaluate(
                """() => {
                     const el = document.querySelector('#projectTitle');
                     if (!el) return '(dialog gone)';
                     let n = el;
                     for (let i = 0; i < 6 && n.parentElement; i++) n = n.parentElement;
                     return (n.innerText || '').replace(/\\s+/g, ' ').slice(0, 600);
                   }"""
            )
            print("   ", container)

        errors = page.evaluate(
            """() => Array.from(document.querySelectorAll('[class*=error],[class*=Error]'))
                 .filter(e => e.offsetParent !== null && (e.textContent || '').trim())
                 .map(e => (e.textContent || '').trim().slice(0, 90))"""
        )
        print("errors after save:", errors)
        still_open = page.locator("#projectTitle").count() and \
            page.locator("#projectTitle").first.is_visible()
        print("dialog still open:", bool(still_open))
    finally:
        browser.close()
