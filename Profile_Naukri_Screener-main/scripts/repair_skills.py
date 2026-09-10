"""Repair key skills: keep an allowlist, drop everything else, add targets.

Both lists come from the `key_skills` section of scripts/profile_edits.yaml.

Key skills are ordered and earlier entries weigh more in recruiter matching, so
`add` is applied in the order you write it. Mirror the exact wording of the
postings you want, including the spellings recruiters actually type.

This DELETES every skill not in `keep`. Read your lists before running it.
"""
import _bootstrap  # noqa: F401  (puts the repo root on sys.path)

from playwright.sync_api import sync_playwright
from naukri.session import open_profile
from naukri import selectors as S
from naukri.apply import _current_chips, _add_one_skill

_SKILLS = _bootstrap.edits("key_skills")
# Compared case-insensitively against what is already on the profile.
KEEP = {str(s).strip().lower() for s in (_SKILLS.get("keep") or []) if str(s).strip()}
# Added verbatim, in this order.
ADD = [str(s).strip() for s in (_SKILLS.get("add") or []) if str(s).strip()]

if not KEEP and not ADD:
    raise SystemExit(
        "\n  scripts/profile_edits.yaml: key_skills has neither 'keep' nor "
        "'add'.\n  An empty keep list would delete every skill on your "
        "profile, so this refuses to run.\n")

with sync_playwright() as p:
    browser, _c, page = open_profile(p, headless=False)
    try:
        for _ in range(8):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)

        page.locator(S.EDITORS["key_skills"]["trigger"][0]).first.click()
        page.wait_for_timeout(3000)

        before = _current_chips(page)
        print(f"BEFORE ({len(before)}):")
        for chip in before:
            print("   ", repr(chip))

        # Remove anything not on the allowlist. Re-query every pass, because
        # removing a chip reindexes the list.
        for _ in range(30):
            chips = page.locator(S.SKILL_CHIP)
            victim = None
            for i in range(chips.count()):
                label = (chips.nth(i).locator(S.SKILL_CHIP_LABEL).inner_text() or "").strip()
                if label.lower() not in KEEP:
                    victim = (i, label)
                    break
            if victim is None:
                break
            i, label = victim
            print(f"  removing: {label!r}")
            page.locator(S.SKILL_CHIP).nth(i).locator(S.SKILL_CHIP_REMOVE).click()
            page.wait_for_timeout(600)

        box = page.locator("#keySkillSugg").first
        box.fill("")
        page.wait_for_timeout(300)

        existing = {c.lower() for c in _current_chips(page)}
        skipped = []
        for skill in ADD:
            if skill.lower() in existing:
                continue
            if _add_one_skill(page, box, skill):
                existing.add(skill.lower())
                print(f"  added: {skill}")
            else:
                skipped.append(skill)

        box.fill("")
        page.wait_for_timeout(400)
        assert box.input_value() == "", "input not empty - would create a junk chip on save"

        final = _current_chips(page)
        print(f"\nAFTER ({len(final)}): {', '.join(final)}")
        if skipped:
            print(f"no exact suggestion match: {', '.join(skipped)}")

        page.locator("#saveKeySkills").click()
        page.wait_for_timeout(3500)
        print("saved")
    finally:
        browser.close()
