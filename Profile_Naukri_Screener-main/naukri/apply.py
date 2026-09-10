"""Push approved rewrites back into Naukri's edit dialogs.

Reads changes.yaml, opens each field's edit dialog, replaces the text and
saves. Runs headed by default so you can watch it and take over if Naukri
throws something unexpected mid-edit.

Nothing is written without either --dry-run being off or an explicit --yes,
because these edits land on a live profile that recruiters are reading.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from . import selectors as S
from .session import DEFAULT_STATE, open_profile

log = logging.getLogger("naukri.apply")

ROOT = Path(__file__).resolve().parent.parent
CHANGES_FILE = ROOT / "changes.yaml"


def load_changes(path: Path = CHANGES_FILE) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"No {path.name} found. Copy changes.example.yaml to changes.yaml and edit it."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(data) - set(S.EDITORS)
    if unknown:
        raise ValueError(
            f"changes.yaml has fields with no editor defined: {sorted(unknown)}. "
            f"Editable fields: {sorted(S.EDITORS)}"
        )
    return data


def _click_first(page, candidates: list[str], what: str) -> None:
    """Click the first candidate selector that is actually clickable."""
    for selector in candidates:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.scroll_into_view_if_needed(timeout=3000)
            locator.click(timeout=5000)
            return
        except Exception as exc:
            log.debug("click %s failed: %s", selector, exc)
    raise RuntimeError(f"Could not find {what}. Selectors tried: {candidates}")


def _fill_first(page, candidates: list[str], value: str, what: str) -> None:
    """Set a field's value and read it back to confirm it landed.

    Uses fill() rather than type(). type() streams keystrokes, and a stream
    still flushing when the next field starts typing interleaves the two
    character by character - which is exactly how a profile summary once ended
    up shredded across the key-skill chips. fill() sets value in one shot.
    """
    for selector in candidates:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.click(timeout=5000)
            locator.fill("", timeout=5000)
            page.wait_for_timeout(200)
            locator.fill(value, timeout=5000)
            page.wait_for_timeout(300)

            wrote = (locator.input_value(timeout=3000) or "").strip()
            if wrote != value.strip():
                raise RuntimeError(
                    f"{what} readback mismatch - wrote {len(value)} chars, "
                    f"field holds {len(wrote)}"
                )
            return
        except Exception as exc:
            log.debug("fill %s failed: %s", selector, exc)
    raise RuntimeError(f"Could not find {what}. Selectors tried: {candidates}")


def _open_editor(page, editor: dict, field: str) -> None:
    """Open a field's dialog and confirm the right one opened.

    Clicking a trigger is not proof the intended dialog appeared - a mis-matched
    selector opens someone else's dialog just as happily. Waiting for this
    field's own input means a wrong dialog raises before any key is pressed,
    rather than after the text has been typed into the wrong box.
    """
    _click_first(page, editor["trigger"], f"{field} edit button")
    page.wait_for_timeout(1200)

    expected = editor["input"][0]
    try:
        page.wait_for_selector(expected, state="visible", timeout=12000)
    except Exception:
        raise RuntimeError(f"{field} dialog did not open (no {expected})")


def _close_editor(page) -> None:
    """Dismiss any open dialog so the next field starts from a clean page."""
    for _ in range(3):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(700)
        except Exception:
            break


CHIP = ".chipsContainer .chip"


def _current_chips(page) -> list[str]:
    """Skill names currently on the chip list, in display order."""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.chipsContainer .chip'))
             .map(c => (c.querySelector('.tagTxt')?.textContent || '').trim())
             .filter(Boolean)"""
    )


def _remove_key_skills(page, unwanted: list[str]) -> list[str]:
    """Click the close icon on each unwanted chip. Returns what was removed."""
    removed = []
    for name in unwanted:
        # Re-query each time - removing a chip reindexes the list.
        chips = page.locator(CHIP)
        for i in range(chips.count()):
            chip = chips.nth(i)
            try:
                label = (chip.locator(".tagTxt").inner_text(timeout=1500) or "").strip()
            except Exception:
                continue
            if label.lower() != name.lower():
                continue
            try:
                chip.locator(".material-icons.close").click(timeout=3000)
                page.wait_for_timeout(500)
                removed.append(label)
            except Exception as exc:
                log.warning("Could not remove chip %s: %s", label, exc)
            break
    return removed


def _apply_key_skills(page, editor: dict, spec) -> None:
    """Sync the key-skill chips.

    `spec` is either a plain list (skills to add) or a mapping with `remove`
    and `add` keys. Removal runs first so freed slots are available to the
    additions - Naukri caps how many skills a profile may carry.
    """
    if isinstance(spec, dict):
        to_remove = spec.get("remove") or []
        to_add = spec.get("add") or []
    else:
        to_remove, to_add = [], list(spec)

    if to_remove:
        removed = _remove_key_skills(page, to_remove)
        print(f"    removed: {', '.join(removed) if removed else 'none'}")

    existing = {s.lower() for s in _current_chips(page)}

    for selector in editor["input"]:
        box = page.locator(selector).first
        if box.count() == 0:
            continue

        skipped = []
        for skill in to_add:
            if skill.lower() in existing:
                continue
            if _add_one_skill(page, box, skill):
                existing.add(skill.lower())
            else:
                skipped.append(skill)

        # Anything still in the box would be committed as a junk chip on save.
        box.fill("")
        page.wait_for_timeout(300)

        if skipped:
            print(f"    no exact match, skipped: {', '.join(skipped)}")
        final = _current_chips(page)
        print(f"    final {len(final)} skills: {', '.join(final)}")
        return

    raise RuntimeError("Could not find the key-skills input.")


def _add_one_skill(page, box, skill: str) -> bool:
    """Type a skill and click its suggestion. True if a chip was created.

    Only an exact (case-insensitive) match is accepted. Taking the first
    suggestion instead would quietly add the wrong skill - typing "Git"
    surfaces "Github" at the top, and a profile claiming skills you did not
    choose is worse than one missing a keyword.
    """
    box.click(timeout=5000)
    box.fill("")
    box.type(skill, delay=40)

    try:
        page.wait_for_selector(S.SKILL_SUGGESTIONS, timeout=5000)
    except Exception:
        box.fill("")
        return False

    options = page.locator(S.SKILL_SUGGESTIONS)
    for i in range(min(options.count(), 12)):
        try:
            label = (options.nth(i).inner_text(timeout=1500) or "").strip()
        except Exception:
            continue
        if label.lower() == skill.lower():
            options.nth(i).click(timeout=3000)
            page.wait_for_timeout(700)
            return True

    box.fill("")
    return False


def apply(
    changes: dict,
    state_path: Path = DEFAULT_STATE,
    headless: bool = False,
    dry_run: bool = True,
) -> dict:
    """Apply each field in `changes`. Returns {field: 'ok' | error message}."""
    from playwright.sync_api import sync_playwright

    if dry_run:
        print("\n  DRY RUN - nothing will be saved.\n")
        for field, value in changes.items():
            preview = ", ".join(value) if isinstance(value, list) else str(value)
            print(f"  {field}:\n    {preview}\n")
        return {field: "dry-run" for field in changes}

    results: dict[str, str] = {}
    with sync_playwright() as p:
        browser, _context, page = open_profile(p, state_path, headless=headless)
        try:
            # Sections below the fold are lazy-rendered. Without this pass their
            # edit buttons genuinely do not exist yet and every trigger lookup
            # for a lower section fails.
            for _ in range(8):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(400)
            page.mouse.wheel(0, -30000)
            page.wait_for_timeout(1200)

            for field, value in changes.items():
                editor = S.EDITORS[field]
                try:
                    _open_editor(page, editor, field)

                    if field == "key_skills":
                        _apply_key_skills(page, editor, value)
                    else:
                        limit = S.MAX_LENGTHS.get(field)
                        text = str(value).strip()
                        if limit and len(text) > limit:
                            raise ValueError(
                                f"{field} is {len(text)} chars, over Naukri's {limit} limit"
                            )
                        _fill_first(page, editor["input"], text, f"{field} input")

                    page.wait_for_timeout(500)
                    _click_first(page, editor["save"], f"{field} save button")
                    page.wait_for_timeout(2500)

                    results[field] = "ok"
                    log.info("Updated %s", field)
                    print(f"  [ok] {field}")
                except Exception as exc:
                    results[field] = str(exc)
                    log.warning("Failed to update %s: %s", field, exc)
                    print(f"  [FAILED] {field}: {exc}")
                finally:
                    # Always, not just on failure: a dialog left open is what
                    # lets one field's text bleed into the next field's input.
                    _close_editor(page)
        finally:
            browser.close()

    return results
