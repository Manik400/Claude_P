"""LinkedIn Easy Apply: submit one application, or say why not.

Same contract as applier.py on the Naukri side. Only Easy Apply postings are
attempted - a job whose Apply button leads to the company's own site is
reported as offsite and left for you.

The Easy Apply dialog is one to four pages: contact info, a resume picker,
the recruiter's "Additional Questions", and a review page with the Submit
button. Every question is answered the same way as on Naukri: from facts on
record (answers.py) or from an answer you gave earlier (questions.py). The
first question that neither can answer stops the attempt - the dialog is
discarded unsubmitted, the question is written to data/jobs/questions.yaml
for you, and the job is retried once you have answered.

LinkedIn ships hashed class names on this dialog and re-rolls them per build,
so nothing here selects on a class. Buttons are found by their visible text
("Next", "Review", "Submit application", "Dismiss", "Discard"), fields by the
<label> that names them, and the dialog itself by walking up from its Dismiss
button. Verified against the live dialog on 2026-09-16.

Statuses:

    applied               submitted and confirmed by LinkedIn
    would-apply           dry run: an Easy Apply button is there, not clicked
    already               the job page says you applied before
    offsite               Apply leads off LinkedIn
    no-button             no apply control (closed posting)
    questionnaire         a question we cannot answer; saved for you
    questionnaire-failed  the form rejected what was entered, or got stuck
    unconfirmed           Submit was clicked but nothing confirmed it
    error                 navigation or interaction failed
    limit-reached         LinkedIn refused: the daily Easy Apply limit is used up
    limit-cooldown        an Easy Apply posting left alone while that limit's
                          24-hour pause holds (linkedin_limit.py); not an attempt
"""
from __future__ import annotations

import logging
import random
import re

from . import answers as answers_mod

log = logging.getLogger("naukri.jobs.linkedin_apply")

EASY_APPLY_BUTTON = "button[aria-label*='Easy Apply' i], button:has-text('Easy Apply')"
# The external Apply is a <button> in the older layout and, in the current
# one, an <a> whose href goes through LinkedIn's "you are leaving" page.
ANY_APPLY_BUTTON = "button:has-text('Apply'), a[href*='linkedin.com/safety/go'], a[href*='/safety/go/']"
DISMISS_BUTTON = "button[aria-label='Dismiss']"
DISCARD_BUTTON = "button:has-text('Discard')"
NEXT_BUTTON = "button:has-text('Next'), button:has-text('Review'), button:has-text('Continue')"
SUBMIT_BUTTON = "button:has-text('Submit application')"

FOLLOW_RE = re.compile(r"^follow\b", re.IGNORECASE)
RESUME_PAGE_RE = re.compile(r"upload a resume|select or upload|be sure to include an updated resume", re.IGNORECASE)
# What LinkedIn shows when the day's Easy Apply allowance is used up. It comes
# as a dialog in place of the form, sometimes as a banner on the job page.
LIMIT_RE = re.compile(
    r"reached (?:the |your )?(?:daily |easy apply )?(?:application |apply )?limit"
    r"|(?:application|apply) limit for today|limit of easy apply|try again tomorrow"
    r"|you can(?:'|’)?t apply to (?:any )?more jobs today", re.IGNORECASE)
CONFIRM_RE = re.compile(r"application (was )?(sent|submitted)|your application (has been|was) (sent|submitted)", re.IGNORECASE)
APPLIED_MARK_RE = re.compile(r"^applied\s+\d|^applied on|^application submitted", re.IGNORECASE)
ERROR_RE = re.compile(r"invalid input|is required|required field|please (enter|select|make a selection)|enter a (valid|decimal|whole) number|select an option", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"^\s*(select an option|select|choose|please select|--)?\s*$", re.IGNORECASE)
YEARS_RE = re.compile(r"\byears?\b|how long|how many", re.IGNORECASE)
PHONE_RE = re.compile(r"phone|mobile", re.IGNORECASE)

# Reads the open dialog: every field, tagged with data-nk="<n>" so Python can
# address it afterwards, plus the buttons, any validation text and the "2/4
# pages" progress marker. Returns {modal: false} when no dialog is open.
SCAN_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  let modal = null;
  for (const d of document.querySelectorAll("button[aria-label='Dismiss']")) {
    let el = d.parentElement, depth = 0;
    while (el && el !== document.body && depth < 12) {
      if (el.getAttribute('role') === 'dialog'
          || el.querySelectorAll('input,select,textarea,button').length > 1) { modal = el; break; }
      el = el.parentElement; depth++;
    }
    if (modal) break;
  }
  if (!modal) return {modal: false};

  const clone = modal.cloneNode(true);
  clone.querySelectorAll('select').forEach(s => s.replaceWith(document.createTextNode(' ')));
  document.body.appendChild(clone);
  const text = norm(clone.innerText);
  clone.remove();

  const byIds = ids => (ids || '').split(' ').map(i => document.getElementById(i))
      .filter(Boolean).map(e => norm(e.innerText)).join(' ');
  const labelOf = el => {
    if (el.id) { const l = modal.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return norm(l.innerText); }
    const wrap = el.closest('label'); if (wrap) return norm(wrap.innerText);
    const lb = byIds(el.getAttribute('aria-labelledby')); if (lb) return lb;
    return el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
  };
  const groupOf = el => {
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) return norm(lg.innerText); }
    const rg = el.closest('[role=radiogroup],[role=group]');
    if (rg) { const t = byIds(rg.getAttribute('aria-labelledby')) || rg.getAttribute('aria-label'); if (t) return norm(t); }
    let p = el.parentElement, depth = 0;
    const own = norm((el.parentElement || {}).innerText || '').length;
    while (p && p !== modal && depth < 6) {
      const t = norm(p.innerText);
      if (t.length < 300 && t.length > own + 3) return t;
      p = p.parentElement; depth++;
    }
    return '';
  };

  const fields = [];
  let idx = 0;
  modal.querySelectorAll('input, select, textarea').forEach(el => {
    if (el.type === 'hidden' || el.type === 'file') return;
    el.setAttribute('data-nk', String(idx));
    const me = idx++;
    if (el.type === 'radio') {
      const opt = {idx: me, label: labelOf(el) || norm((el.parentElement || {}).innerText || '').slice(0, 80), checked: el.checked};
      const last = fields[fields.length - 1];
      if (last && last.kind === 'radio' && last.name === el.name) { last.options.push(opt); return; }
      fields.push({kind: 'radio', name: el.name, label: groupOf(el), options: [opt],
                   required: el.required || el.getAttribute('aria-required') === 'true'});
      return;
    }
    const kind = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : (el.type || 'text');
    const field = {kind, idx: me, label: labelOf(el) || groupOf(el).slice(0, 160), value: el.value || '',
                   checked: !!el.checked, required: el.required || el.getAttribute('aria-required') === 'true'};
    if (kind === 'select') {
      field.options = Array.from(el.options).map(o => o.text);
      field.selected = el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '';
    }
    fields.push(field);
  });

  const buttons = Array.from(modal.querySelectorAll('button'))
      .map(b => norm(b.innerText) || b.getAttribute('aria-label') || '').filter(Boolean);
  const progress = (text.match(/\d+\s*\/\s*\d+\s*pages?/i) || [''])[0];
  return {modal: true, text, fields, buttons, progress};
}
"""


def _field(page, idx: int):
    return page.locator(f'[data-nk="{idx}"]').first


def _click_input(page, idx: int) -> None:
    """Tick a radio or checkbox whose <input> may be visually hidden behind a
    styled label - a normal click fails the visibility check, a JS click
    still fires React's change handler."""
    locator = _field(page, idx)
    try:
        locator.click(timeout=3000, force=True)
    except Exception:
        locator.evaluate("el => el.click()")


def _errors(info: dict) -> str:
    found = ERROR_RE.findall(info.get("text") or "")
    return ", ".join(sorted(set(f.lower() for f in found))) if found else ""


def _whole_number(answer: str) -> str:
    """LinkedIn's "years of experience" boxes want a whole number."""
    match = re.search(r"\d+(?:\.\d+)?", answer or "")
    if not match:
        return answer
    return str(int(round(float(match.group()))))


def _dismiss(page, discard: bool) -> None:
    """Close the dialog. `discard` answers the "save this application?"
    prompt with Discard, so an abandoned attempt leaves nothing half-done."""
    try:
        closer = page.locator(DISMISS_BUTTON).first
        if closer.count():
            closer.click(timeout=4000)
            page.wait_for_timeout(1200)
    except Exception as exc:
        log.debug("dismiss click failed: %s", exc)
    if not discard:
        return
    try:
        button = page.locator(DISCARD_BUTTON).first
        if button.count() and button.is_visible(timeout=1500):
            button.click(timeout=4000)
            page.wait_for_timeout(800)
    except Exception as exc:
        log.debug("discard click failed: %s", exc)


def _already_applied(page) -> bool:
    try:
        return page.get_by_text(APPLIED_MARK_RE).first.is_visible(timeout=1500)
    except Exception:
        return False


def _fill_page(page, info: dict, facts: dict, phone: str | None, capture: dict) -> tuple[bool, str]:
    """Fill every empty field on the page. Returns (ok, note).

    ok=False means a field needs an answer we do not have; `capture` then
    holds the question and its options for questions.record(). Every field
    that IS filled is appended to capture["answers"] for the applications log.
    """
    resume_page = bool(RESUME_PAGE_RE.search(info.get("text") or ""))

    def remember(question: str, options: list[str], answer, source: str) -> None:
        capture.setdefault("answers", []).append(
            {"question": question, "options": list(options), "answer": answer, "source": source})
    for field in info["fields"]:
        kind = field["kind"]
        label = (field.get("label") or "").strip()

        if kind == "checkbox":
            # "Follow <company> to stay up to date" is ticked by default on the
            # review page. Applying is not subscribing; untick it.
            if FOLLOW_RE.match(label) and field.get("checked"):
                _click_input(page, field["idx"])
            continue

        if kind == "radio":
            options = field["options"]
            if any(o.get("checked") for o in options):
                continue
            labels = [o["label"] for o in options]
            if resume_page and not label.endswith("?"):
                # The resume picker: rows named after the files. The newest
                # upload is listed first, and it is the one you keep current.
                _click_input(page, options[0]["idx"])
                remember("Resume", labels[:5], options[0]["label"], "newest resume on LinkedIn")
                continue
            answer, why = answers_mod.resolve(label, labels, facts)
            if answer is None:
                capture.update(question=label, options=labels, why=why)
                return False, why
            choice = answers_mod.choose_option(answer, labels)
            if choice is None:
                capture.update(question=label, options=labels,
                               why=f"resolved to {answer!r}, which matches none of the options")
                return False, f"{answer!r} matches none of {labels}"
            for option in options:
                if option["label"] == choice:
                    _click_input(page, option["idx"])
                    break
            remember(label, labels, choice, why)
            page.wait_for_timeout(random.uniform(300, 700))
            continue

        if kind == "select":
            selected = (field.get("selected") or "").strip()
            options = [o for o in field.get("options") or [] if not PLACEHOLDER_RE.match(o)]
            if selected and not PLACEHOLDER_RE.match(selected):
                continue
            if not options:
                continue
            answer, why = answers_mod.resolve(label, options, facts)
            if answer is None:
                capture.update(question=label, options=options, why=why)
                return False, why
            choice = answers_mod.choose_option(answer, options)
            if choice is None:
                capture.update(question=label, options=options,
                               why=f"resolved to {answer!r}, which matches none of the options")
                return False, f"{answer!r} matches none of {options}"
            try:
                _field(page, field["idx"]).select_option(label=choice, timeout=4000)
            except Exception as exc:
                return False, f"could not select {choice!r}: {str(exc)[:80]}"
            remember(label, options, choice, why)
            page.wait_for_timeout(random.uniform(300, 700))
            continue

        if kind in ("text", "number", "textarea", "tel", "email", "search", "url"):
            if (field.get("value") or "").strip():
                continue
            if kind == "tel" or PHONE_RE.search(label):
                if not phone:
                    capture.update(question=label or "Phone number", options=[],
                                   why="no phone number on record - set answers.phone in jobs.yaml")
                    return False, "no phone number on record (answers.phone in jobs.yaml)"
                _field(page, field["idx"]).fill(phone, timeout=4000)
                remember(label or "Phone number", [], phone, "answers.phone in jobs.yaml")
                continue
            if kind == "email":
                continue
            answer, why = answers_mod.resolve(label, [], facts)
            if answer is None:
                capture.update(question=label, options=[], why=why)
                return False, why
            if kind == "number" or YEARS_RE.search(label):
                answer = _whole_number(answer)
            try:
                box = _field(page, field["idx"])
                box.click(timeout=3000)
                box.fill(str(answer), timeout=4000)
            except Exception as exc:
                return False, f"could not type into '{label[:50]}': {str(exc)[:80]}"
            remember(label, [], answer, why)
            page.wait_for_timeout(random.uniform(300, 700))
            continue
    return True, ""


def _limit_text(page) -> str:
    """The limit message on the page or in its dialog, or ""."""
    try:
        body = page.locator("body").inner_text(timeout=3000) or ""
    except Exception:
        return ""
    m = LIMIT_RE.search(body)
    return m.group(0) if m else ""


def apply_to(page, card: dict, facts: dict, dry_run: bool = True,
             phone: str | None = None, capture: dict | None = None,
             easy_apply_paused: bool = False) -> tuple[str, str]:
    """Attempt one Easy Apply. Returns (status, note); see the module doc.

    `card` is a search-result card (url, title, company). `capture`, if
    given, receives {question, options, why} when a question stops the run.
    `easy_apply_paused` (the daily limit's cooldown) opens the posting only
    to tell Easy Apply from an offsite Apply: the first is left alone, the
    second is still reported "offsite" so the career applier can follow it.
    """
    capture = capture if capture is not None else {}
    try:
        page.goto(card["url"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(random.uniform(3500, 5500))
    except Exception as exc:
        return "error", f"navigation failed: {str(exc)[:120]}"

    if _already_applied(page):
        return "already", "job page says you applied before"

    button = page.locator(EASY_APPLY_BUTTON).first
    try:
        has_easy = button.count() > 0 and button.is_visible(timeout=4000)
    except Exception:
        has_easy = False
    if not has_easy:
        try:
            other = page.locator(ANY_APPLY_BUTTON).first
            if other.count() and other.is_visible(timeout=2000):
                return "offsite", "Apply leads off LinkedIn"
        except Exception:
            pass
        return "no-button", "no apply control found"

    if easy_apply_paused:
        return "limit-cooldown", "Easy Apply paused: LinkedIn's daily limit was reached earlier"
    if dry_run:
        return "would-apply", "Easy Apply button present"

    try:
        button.click(timeout=8000)
    except Exception as exc:
        return "error", f"Easy Apply click failed: {str(exc)[:120]}"
    page.wait_for_timeout(random.uniform(3500, 5500))

    previous = None
    stuck = 0
    for step in range(12):
        info = page.evaluate(SCAN_JS)
        if step == 0:
            hit = LIMIT_RE.search(info.get("text") or "")
            hit = hit.group(0) if hit else _limit_text(page)
            if hit:
                _dismiss(page, discard=True)
                return "limit-reached", f"LinkedIn says '{hit}'"
        if not info.get("modal"):
            if _already_applied(page):
                return "applied", "job page shows Applied"
            return "unconfirmed", "dialog closed without a confirmation"
        if CONFIRM_RE.search(info.get("text") or ""):
            _dismiss(page, discard=False)
            return "applied", "LinkedIn confirmed the application"

        signature = (info.get("progress"), tuple(f.get("label") for f in info["fields"]))
        stuck = stuck + 1 if signature == previous else 0
        previous = signature
        if stuck >= 2:
            note = _errors(info) or "the page did not advance"
            _dismiss(page, discard=True)
            return "questionnaire-failed", f"stuck on {info.get('progress') or 'a page'}: {note}"

        ok, note = _fill_page(page, info, facts, phone, capture)
        if not ok:
            _dismiss(page, discard=True)
            return "questionnaire", f"cannot answer '{capture.get('question', '')[:70]}' - {note}"
        page.wait_for_timeout(random.uniform(600, 1200))

        labels = [b.lower() for b in info.get("buttons") or []]
        if any("submit application" in b for b in labels):
            try:
                page.locator(SUBMIT_BUTTON).first.click(timeout=8000)
            except Exception as exc:
                _dismiss(page, discard=True)
                return "error", f"Submit click failed: {str(exc)[:120]}"
            after = {}
            for _ in range(10):
                page.wait_for_timeout(1000)
                after = page.evaluate(SCAN_JS)
                if not after.get("modal") or CONFIRM_RE.search(after.get("text") or ""):
                    break
            if after.get("modal") and CONFIRM_RE.search(after.get("text") or ""):
                _dismiss(page, discard=False)
                return "applied", "LinkedIn confirmed the application"
            if after.get("modal") and _errors(after):
                _dismiss(page, discard=True)
                return "questionnaire-failed", f"Submit refused: {_errors(after)}"
            _dismiss(page, discard=False)
            page.wait_for_timeout(1500)
            if _already_applied(page):
                return "applied", "job page shows Applied"
            return "unconfirmed", "Submit clicked, but nothing confirmed it"

        nxt = page.locator(NEXT_BUTTON).first
        if not nxt.count():
            _dismiss(page, discard=True)
            return "questionnaire-failed", "no Next, Review or Submit button on the page"
        try:
            nxt.click(timeout=8000)
        except Exception as exc:
            _dismiss(page, discard=True)
            return "error", f"Next click failed: {str(exc)[:120]}"
        page.wait_for_timeout(random.uniform(2500, 4000))

    _dismiss(page, discard=True)
    return "questionnaire-failed", "gave up after 12 pages"
