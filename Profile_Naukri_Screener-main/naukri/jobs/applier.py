"""Apply to a single job, or decline to and say why.

One rule shapes this module: it never answers a recruiter's screening
questions. When a posting opens a questionnaire, the application is not yet
submitted, and finishing it means inventing answers about your notice period,
your salary expectation or your willingness to relocate. Those answers are
yours to give. The drawer is closed, the job goes to the review queue, and you
answer it in a browser.

Every return value is one of:

    applied       the application was submitted and confirmed
    already       Naukri says you had applied to this before
    offsite       apply leads to the company's own portal
    questionnaire a screening questionnaire opened; left unanswered for you
    unconfirmed   the click landed but no confirmation appeared
    no-button     no apply control on the page
    error         navigation or interaction failed
"""
from __future__ import annotations

import logging
import random
import time

from .. import selectors as S

log = logging.getLogger("naukri.jobs.applier")


def _first_visible(page, candidates: list[str], timeout: int = 3000):
    for selector in candidates:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=timeout):
                return locator
        except Exception:
            continue
    return None


def _any_visible(page, candidates: list[str], timeout: int = 1500) -> bool:
    return _first_visible(page, candidates, timeout) is not None


def _current_question(page) -> str | None:
    """The last thing the bot said, which is the question on screen."""
    try:
        messages = page.locator(S.CHATBOT_QUESTION)
        count = messages.count()
        if not count:
            return None
        return (messages.nth(count - 1).inner_text(timeout=2000) or "").strip() or None
    except Exception:
        return None


def _current_options(page) -> list[str]:
    """Visible choice labels for the question on screen, if it has any."""
    out = []
    try:
        labels = page.locator(S.CHATBOT_RADIO_LABEL)
        for i in range(min(labels.count(), 25)):
            label = labels.nth(i)
            if not label.is_visible(timeout=500):
                continue
            text = (label.inner_text(timeout=1000) or "").strip()
            if text:
                out.append(text)
    except Exception:
        pass
    return out


def _submit_answer(page) -> bool:
    """Click Save. Returns False if it is still disabled, meaning the answer
    did not register - clicking anyway would send an empty response."""
    try:
        if page.locator(S.CHATBOT_SAVE_DISABLED).count():
            return False
        save = page.locator(S.CHATBOT_SAVE).first
        if not save.count():
            return False
        save.click(timeout=5000)
        page.wait_for_timeout(1800)
        return True
    except Exception as exc:
        log.debug("save click failed: %s", exc)
        return False


def _confirm_applied(page, allow_reload: bool = True) -> bool:
    """Ask the job page itself whether the application landed.

    The chatbot does not reliably announce success - it may simply run out of
    questions and close. The page's own "Applied" badge is the ground truth,
    so check that, reloading once if it has not repainted yet.
    """
    for attempt in range(2):
        if _any_visible(page, S.APPLY_APPLIED_MARKERS, timeout=2000):
            return True
        if _any_visible(page, S.APPLY_SUCCESS, timeout=1000):
            return True
        if not allow_reload or attempt:
            break
        try:
            page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
        except Exception as exc:
            log.debug("reload while confirming failed: %s", exc)
            break
    return False


def _wait_for_question(page, previous: str | None, timeout: float = 15.0) -> str | None:
    """Wait for a question that is not the one we just answered.

    The bot renders its messages after the drawer animates in, and again after
    each Save, so reading immediately gets an empty list - which is what made
    the first live attempt report "answered 0".
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        question = _current_question(page)
        if question and question != previous:
            return question
        if _any_visible(page, S.CHATBOT_SUCCESS, timeout=300):
            return None
        page.wait_for_timeout(500)
    return None


def _fill_questionnaire(page, facts: dict, max_questions: int = 15) -> tuple[str, str]:
    """Answer the screening questions, but only from facts.

    Stops at the first question that cannot be grounded in a fact and leaves
    the rest unanswered, so a partially-answerable questionnaire ends up in
    your queue rather than half-submitted with a guess in it.

    Two failure statuses, deliberately distinct:
      questionnaire         a genuine refusal - it asked something we cannot
                            know. Retrying tomorrow changes nothing.
      questionnaire-failed  a mechanical problem - stuck, disabled Save, an
                            input type we do not drive. Worth retrying.
    """
    from . import answers as answers_mod

    answered: list[str] = []
    previous: str | None = None

    for _ in range(max_questions):
        if _any_visible(page, S.CHATBOT_SUCCESS, timeout=800):
            return "applied", f"answered {len(answered)} question(s): {'; '.join(answered)}"

        question = _wait_for_question(page, previous)
        if not question:
            break
        previous = question

        options = _current_options(page)
        log.debug("questionnaire asks %r with options %s", question[:80], options)
        answer, reason = answers_mod.resolve(question, options, facts)
        if answer is None:
            _close_questionnaire(page)
            return "questionnaire", f"cannot answer '{question[:70]}' - {reason}"

        if options:
            choice = answers_mod.choose_option(answer, options)
            if choice is None:
                _close_questionnaire(page)
                return "questionnaire-failed", (
                    f"'{question[:50]}' - resolved to {answer!r}, "
                    f"which matches none of {options}"
                )
            try:
                page.locator(S.CHATBOT_RADIO_LABEL, has_text=choice).first.click(timeout=4000)
            except Exception:
                try:
                    page.get_by_text(choice, exact=True).first.click(timeout=4000)
                except Exception as exc:
                    _close_questionnaire(page)
                    return "questionnaire-failed", f"could not select {choice!r}: {str(exc)[:80]}"
            page.wait_for_timeout(600)
            answered.append(f"{question[:40]} -> {choice}")
        else:
            box = _first_visible(page, [S.CHATBOT_TEXT_INPUT], timeout=3000)
            if box is None:
                # Neither choices nor a text box: an input type we have not
                # verified (multi-select, date, file upload). Do not improvise.
                _close_questionnaire(page)
                return "questionnaire-failed", f"unsupported input for '{question[:60]}'"
            try:
                box.click(timeout=3000)
                box.fill("") if hasattr(box, "fill") else None
                page.keyboard.type(str(answer), delay=40)
            except Exception as exc:
                _close_questionnaire(page)
                return "questionnaire-failed", f"could not type answer: {str(exc)[:80]}"
            page.wait_for_timeout(500)
            answered.append(f"{question[:40]} -> {answer}")

        if not _submit_answer(page):
            _close_questionnaire(page)
            return "questionnaire-failed", f"Save stayed disabled after answering '{question[:50]}'"
        page.wait_for_timeout(1200)

    _close_questionnaire(page)
    if _confirm_applied(page):
        return "applied", f"answered {len(answered)} question(s): {'; '.join(answered)}"
    return "questionnaire-failed", f"answered {len(answered)} but the job page does not say Applied"


def _close_questionnaire(page) -> None:
    """Dismiss the screening drawer without answering anything."""
    closer = _first_visible(page, S.JOB_CHATBOT_CLOSE, timeout=2000)
    if closer:
        try:
            closer.click(timeout=3000)
            page.wait_for_timeout(600)
            return
        except Exception as exc:
            log.debug("questionnaire close click failed: %s", exc)
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass


def apply_to(page, job, dry_run: bool = True, facts: dict | None = None) -> tuple[str, str]:
    """Attempt one application. Returns (status, note).

    With dry_run the page is opened and the apply control inspected, but never
    clicked - so a dry run reports exactly what a real run would do without
    sending anything.

    `facts` enables answering screening questions. Pass None (the default) and
    any questionnaire is closed unanswered and queued for you.
    """
    try:
        page.goto(job.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(random.uniform(2200, 4200))
    except Exception as exc:
        return "error", f"navigation failed: {str(exc)[:120]}"

    button = _first_visible(page, S.JOB_APPLY_BUTTON, timeout=6000)
    if button is None:
        # No apply control usually means the posting has closed or already
        # carries an application.
        if _any_visible(page, S.APPLY_SUCCESS):
            return "already", "no button; page shows an existing application"
        return "no-button", "no apply control found"

    try:
        label = (button.inner_text(timeout=3000) or "").strip().lower()
    except Exception:
        label = ""

    if any(marker in label for marker in S.APPLY_DONE_LABELS):
        return "already", f"button reads '{label}'"
    if any(marker in label for marker in S.APPLY_OFFSITE_LABELS):
        return "offsite", f"button reads '{label}'"

    if dry_run:
        return "would-apply", f"button reads '{label or 'Apply'}'"

    try:
        button.click(timeout=8000)
    except Exception as exc:
        return "error", f"apply click failed: {str(exc)[:120]}"

    # Two things can happen next and they are not mutually exclusive in
    # timing - poll for both rather than waiting on either alone.
    deadline = time.time() + 15
    while time.time() < deadline:
        if _any_visible(page, S.JOB_CHATBOT, timeout=700):
            if facts:
                return _fill_questionnaire(page, facts)
            _close_questionnaire(page)
            return "questionnaire", "screening questions opened; left for you to answer"
        if _any_visible(page, S.APPLY_SUCCESS, timeout=700):
            return "applied", "confirmation shown"
        page.wait_for_timeout(500)

    # No confirmation and no questionnaire. The click may still have landed,
    # so this is reported as unconfirmed rather than as either outcome - the
    # ledger treats it as non-terminal and the report flags it for a look.
    if _confirm_applied(page):
        return "applied", "job page now shows Applied"
    return "unconfirmed", "clicked, but the job page does not say Applied"
