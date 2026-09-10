"""Add past roles to Naukri so employment matches the resume.

Naukri drops the salary, notice-period and key-skill fields once a job is
marked as past, so a previous role needs only company, designation, the two
date pairs and a description. Those come from the `past_employment` section of
scripts/profile_edits.yaml.

Recruiter search filters on the total-experience header, NOT on the sum of the
employment entries - so after running this, run set_total_experience.py or the
additions buy you no visibility.
"""
import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

from playwright.sync_api import sync_playwright
from naukri.session import open_profile


def jobs() -> list[dict]:
    """The roles to add, normalised from profile_edits.yaml.

    `from`/`to` are accepted as either [month, year] or "Oct 2021", because
    both read naturally in YAML and getting it wrong is otherwise a Playwright
    timeout twenty seconds into a live profile edit.
    """
    def when(value, field, company):
        if isinstance(value, str):
            value = value.split()
        parts = [str(bit).strip() for bit in (value or []) if str(bit).strip()]
        if len(parts) != 2:
            raise _bootstrap.EditsError(
                f"past_employment entry for {company!r}: '{field}' should be "
                f"[month, year], e.g. [Oct, 2021] - got {value!r}")
        return tuple(parts)

    out = []
    for entry in _bootstrap.edits("past_employment"):
        company = entry.get("company")
        missing = [k for k in ("company", "designation", "from", "to", "desc")
                   if not entry.get(k)]
        if missing:
            raise _bootstrap.EditsError(
                f"past_employment entry {company or '(unnamed)'} is missing: "
                f"{', '.join(missing)}")
        out.append({
            "company": company,
            "designation": entry["designation"],
            "from": when(entry["from"], "from", company),
            "to": when(entry["to"], "to", company),
            "desc": entry["desc"].strip(),
        })
    return out


def suggest(page, field_id: str, value: str) -> str:
    """Fill a suggestor, clicking an exact suggestion when one is on screen.

    The dropdown can exist in the DOM while hidden; clicking it then hangs
    until timeout. Free text is accepted by these fields, so an invisible or
    non-matching list is not an error.
    """
    box = page.locator(f"#{field_id}").first
    box.click()
    box.fill("")
    box.type(value, delay=40)
    page.wait_for_timeout(2000)

    opts = page.locator(f"#sugDrp_{field_id} li.sugTouple")
    if opts.count() and opts.first.is_visible():
        for i in range(min(opts.count(), 10)):
            if (opts.nth(i).inner_text() or "").strip().lower() == value.lower():
                opts.nth(i).click()
                page.wait_for_timeout(700)
                break
    return box.input_value()


def pick(page, droope: str, want: str) -> str:
    page.locator(f"#{droope}For").first.click()
    page.wait_for_timeout(1100)
    page.locator(f"#ul_{droope} li.pickVal a", has_text=want).first.click()
    page.wait_for_timeout(900)
    return page.locator(f"#{droope}For").first.input_value()


def add(page, job: dict) -> None:
    for _ in range(8):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(400)

    page.locator("xpath=//*[normalize-space(text())='Add employment']").first.click()
    page.wait_for_selector("#companySugg", state="visible", timeout=15000)
    page.wait_for_timeout(1500)

    page.locator("label[for='no']").first.click()
    page.wait_for_timeout(1500)
    assert page.locator("#no").first.is_checked(), "could not mark as past employment"

    print("  company:    ", repr(suggest(page, "companySugg", job["company"])))
    print("  designation:", repr(suggest(page, "designationSugg", job["designation"])))
    print("  from:", pick(page, "startedMonth", job["from"][0]),
          pick(page, "startedYear", job["from"][1]))
    print("  to:  ", pick(page, "workedTillMonth", job["to"][0]),
          pick(page, "workedTillYear", job["to"][1]))

    page.locator("#jobDescription").first.fill(job["desc"])
    page.wait_for_timeout(500)
    print("  desc len:", len(page.locator("#jobDescription").first.input_value()))

    page.locator("#submitEmployment").click()
    page.wait_for_timeout(5000)

    still_open = page.locator("#companySugg").count() and \
        page.locator("#companySugg").first.is_visible()
    if still_open:
        # Naukri reports a blocked save only as inline text inside the dialog.
        text = page.evaluate(
            """() => {
                 const el = document.querySelector('#companySugg');
                 let n = el;
                 for (let i = 0; i < 7 && n.parentElement; i++) n = n.parentElement;
                 return (n.innerText || '').replace(/\\s+/g, ' ').slice(0, 500);
               }"""
        )
        raise RuntimeError(f"save blocked, dialog text: {text}")
    print("  saved")


def main() -> None:
    to_add = jobs()
    print(f"{len(to_add)} role(s) to add, from scripts/profile_edits.yaml")
    with sync_playwright() as p:
        browser, _c, page = open_profile(p, headless=False)
        try:
            for job in to_add:
                print(f"\n{job['designation']} at {job['company']}")
                add(page, job)
                page.goto("https://www.naukri.com/mnjuser/profile",
                          wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(main))
