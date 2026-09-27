"""The verification code an application form e-mails you, read from your inbox.

Greenhouse (MongoDB, and more boards every month) will not take an application
until the 8-character code it just e-mailed is typed back. The screener already
reads your Gmail over IMAP for recruiter replies (responses.py, an app password
you can revoke); this looks there for a code that arrived in the last few
minutes and hands it to the form - the same thing you would do by hand.

    python -m naukri.jobs.mailcode          show the newest code, if any
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import responses

log = logging.getLogger("naukri.jobs.mailcode")

SUBJECT_HINT = re.compile(r"verif|confirm|code|one.?time|otp|security", re.I)
# "Your verification code is ABCD1234" / "code: 482913" - 6 to 8 characters, not a year or a phone
CODE_PATTERNS = [
    re.compile(r"(?:code|otp)\W{0,40}?\b([A-Z0-9]{8})\b"),
    re.compile(r"(?:code|otp)\W{0,40}?\b(\d{6})\b", re.I),
    re.compile(r"\b([A-Z0-9]{8})\b(?=\W{0,40}(?:is your|to (?:verify|confirm|complete)))"),
    re.compile(r"(?:code|otp)\W{0,40}?\b([A-Za-z0-9]{6,8})\b", re.I),
]


def configured() -> bool:
    return responses.configured()


def _text(message) -> str:
    parts = []
    for part in message.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
            except Exception:
                continue
    text = " ".join(parts)
    return re.sub(r"<[^>]+>", " ", text)


def _find_code(text: str) -> str | None:
    for pattern in CODE_PATTERNS:
        m = pattern.search(text)
        if m and not re.fullmatch(r"(19|20)\d{2}", m.group(1)):
            return m.group(1)
    return None


def latest_code(minutes: int = 15, sent_to: str | None = None) -> str | None:
    """The code in the newest verification e-mail of the last `minutes`, or None."""
    config = responses.load_config()
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes))
    box = imaplib.IMAP4_SSL(responses.IMAP_HOST)
    try:
        box.login(config["email"], config["app_password"])
        box.select("INBOX", readonly=True)
        _status, data = box.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        ids = (data[0] or b"").split()[-40:]
        best: tuple[datetime, str] | None = None
        for mid in reversed(ids):
            _s, raw = box.fetch(mid, "(RFC822)")
            if not raw or not raw[0]:
                continue
            message = email.message_from_bytes(raw[0][1])
            try:
                when = parsedate_to_datetime(message.get("Date"))
                when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            except Exception:
                when = datetime.now(timezone.utc)
            if when < since:
                continue
            subject = str(message.get("Subject") or "")
            body = _text(message)
            if not SUBJECT_HINT.search(subject + " " + body[:300]):
                continue
            code = _find_code(subject + "\n" + body)
            if code and (best is None or when > best[0]):
                best = (when, code)
        return best[1] if best else None
    finally:
        try:
            box.logout()
        except Exception:
            pass


def wait_for_code(wait_s: int = 90, minutes: int = 15) -> str | None:
    """Poll the inbox until a fresh code arrives (the e-mail takes a few seconds to land)."""
    if not configured():
        return None
    end = time.monotonic() + wait_s
    while True:
        try:
            code = latest_code(minutes=minutes)
        except Exception as exc:  # noqa: BLE001 - a mail hiccup must not sink the form
            log.debug("mail check failed: %s", exc)
            code = None
        if code or time.monotonic() >= end:
            return code
        time.sleep(8)


if __name__ == "__main__":
    print(latest_code() if configured() else "Gmail is not set up (dashboard -> Settings -> Gmail)")
