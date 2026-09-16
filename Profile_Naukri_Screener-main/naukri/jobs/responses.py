"""What came back: recruiter replies in your Gmail, matched to applications.

Reads your inbox over IMAP with a Gmail *app password* (never your real
password - Google issues app passwords under Security > 2-Step Verification >
App passwords, and you can revoke one any time). Credentials live in
data/gmail.yaml, which is gitignored with the rest of data/:

    email: you@gmail.com
    app_password: xxxx xxxx xxxx xxxx

Every sync pulls the last `days` of mail from the job boards and recruiters,
classifies each message - viewed, shortlisted, interview, rejected,
confirmation - and attaches it to the application whose company or title it
mentions. Results are kept in data/jobs/responses.json and shown in the
dashboard's Applications tab. Nothing is ever sent, moved or deleted; the
mailbox is opened read-only.
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

log = logging.getLogger("naukri.jobs.responses")

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "data" / "gmail.yaml"
STORE_PATH = ROOT / "data" / "jobs" / "responses.json"

IMAP_HOST = "imap.gmail.com"

# Senders worth reading at all. Everything else in the inbox is skipped
# without being downloaded.
SENDER_HINTS = ("naukri", "linkedin", "recruit", "talent", "hiring", "careers", "jobs", "hr@", "hr.",
                "noreply", "no-reply", "workday", "greenhouse", "lever.co", "smartrecruiters",
                "zoho", "darwinbox", "keka", "freshteam", "ashby", "taleo", "successfactors",
                "icims", "jobvite", "hirist", "instahyre", "cutshort", "wellfound", "indeed", "glassdoor")

# Ordered: the first kind whose pattern matches wins, so a "we regret" beats
# the word "interview" in the same rejection letter.
KINDS: list[tuple[str, str]] = [
    ("rejected", r"unfortunately|regret|not (been )?(selected|shortlisted)|not moving forward|"
                 r"decided to (move forward|proceed) with other|no longer (under )?consider|"
                 r"will not be (moving|proceeding)|position has been filled|not a (match|fit) at this time"),
    ("interview", r"interview|schedule a (call|discussion|meeting)|technical (round|discussion|test)|"
                  r"assessment|coding (test|challenge|round)|hackerrank|codility|hackerearth|"
                  r"please (confirm|share) your availability|online test"),
    ("shortlisted", r"shortlist|interested in your (profile|candidature)|would like to (connect|discuss|talk)|"
                    r"your profile (has been |was )?(selected|matches)|next (step|round)|screening call"),
    ("viewed", r"(viewed|seen) your (application|profile|resume)|application (was|has been) viewed|"
               r"recruiter (viewed|looked at)|profile (was )?viewed"),
    ("confirmation", r"application (was |has been )?(sent|submitted|received)|thank you for applying|"
                     r"applied (successfully|for)|we have received your application|you applied"),
]

KIND_LABELS = {
    "rejected": "Rejected",
    "interview": "Interview / test",
    "shortlisted": "Shortlisted",
    "viewed": "Viewed",
    "confirmation": "Application received",
    "other": "Reply",
}

# Rank of a kind when picking the latest meaningful status per application.
KIND_RANK = {"rejected": 5, "interview": 4, "shortlisted": 3, "viewed": 2, "other": 1, "confirmation": 0}

STOPWORDS = {"the", "and", "pvt", "ltd", "private", "limited", "inc", "llp", "technologies", "technology",
             "solutions", "services", "software", "systems", "india", "global", "consulting", "group",
             "labs", "engineer", "developer", "senior", "junior", "sde", "software", "backend", "frontend",
             "full", "stack", "fullstack", "java", "python", "intern", "remote", "freelancer", "ii", "i"}


class GmailNotConfigured(RuntimeError):
    """data/gmail.yaml is missing or incomplete."""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise GmailNotConfigured(f"No Gmail settings at {CONFIG_PATH}. Save them in the dashboard's Settings tab.")
    try:
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GmailNotConfigured(f"{CONFIG_PATH} is not valid YAML: {exc}")
    address = str(data.get("email") or "").strip()
    password = str(data.get("app_password") or "").replace(" ", "").strip()
    if not address or not password:
        raise GmailNotConfigured("Gmail settings need both `email` and `app_password`.")
    return {"email": address, "app_password": password, "days": int(data.get("days") or 30)}


def save_config(address: str, app_password: str, days: int = 30) -> Path:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = {"email": address.strip(), "app_password": app_password.strip(), "days": int(days)}
    CONFIG_PATH.write_text(
        "# Gmail app password for reading recruiter replies. Revoke it at\n"
        "# https://myaccount.google.com/apppasswords if this file ever leaks.\n"
        + yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return CONFIG_PATH


def configured() -> bool:
    try:
        load_config()
        return True
    except GmailNotConfigured:
        return False


def load_store() -> dict:
    if not STORE_PATH.exists():
        return {"synced_at": None, "emails": []}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("emails"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"synced_at": None, "emails": []}


def save_store(store: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- matching

def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def classify(subject: str, body: str) -> str:
    text = f"{subject}\n{body}".lower()
    for kind, pattern in KINDS:
        if re.search(pattern, text):
            return kind
    return "other"


def match_applications(message: dict, applications: list[dict]) -> list[str]:
    """Job ids of the applications this message is about.

    A company-name token in the subject, sender or body is the signal; a
    title match on its own is too weak (every board mails about "Backend
    Developer" jobs). Confirmation and viewed mails from a board name the
    posting, so those match on company and title together when possible.
    """
    hay = f"{message.get('from', '')}\n{message.get('subject', '')}\n{message.get('body', '')}".lower()
    hay_flat = re.sub(r"[^a-z0-9]+", " ", hay)
    hay_tokens = tokens(hay)
    hits: list[tuple[int, str]] = []
    for app in applications:
        if app.get("status") != "applied":
            continue
        name = re.sub(r"[^a-z0-9]+", " ", (app.get("company") or "").lower()).strip()
        company = tokens(app.get("company", ""))
        if not name:
            continue
        # The whole name as a phrase ("soul ai", "tripjack") is the strongest
        # signal; single tokens catch "Tripjack's careers team" style mentions.
        phrase = f" {name} " in f" {hay_flat} "
        overlap = company & hay_tokens
        if not phrase and not overlap:
            continue
        score = (5 if phrase else 0) + len(overlap) * 2
        title_hits = tokens(app.get("title", "")) & hay_tokens
        score += len(title_hits)
        # A company name that is one common word ("matched") needs the title
        # as well, or every mail using the word attaches to it.
        if not phrase and len(company) == 1 and not title_hits and len(next(iter(company))) < 7:
            continue
        if phrase and len(name) < 5 and not title_hits and not overlap:
            continue
        hits.append((score, app.get("job_id", "")))
    hits.sort(reverse=True)
    return [job_id for _, job_id in hits[:5] if job_id]


# -------------------------------------------------------------------- IMAP

def _decode(value) -> str:
    if not value:
        return ""
    parts = []
    for text, charset in email.header.decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def _body_text(message) -> str:
    chunks = []
    for part in message.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        if part.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if part.get_content_type() == "text/html":
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&nbsp;|&#160;", " ", text)
            text = re.sub(r"&amp;", "&", text)
        chunks.append(text)
        if part.get_content_type() == "text/plain":
            break
    text = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    return text[:4000]


def _interesting(sender: str, subject: str) -> bool:
    low = f"{sender} {subject}".lower()
    return any(hint in low for hint in SENDER_HINTS) or bool(
        re.search(r"application|interview|shortlist|candidat|position|opportunity|hiring|job", low))


def fetch(config: dict, days: int | None = None, limit: int = 400) -> list[dict]:
    """Recent job-related mail, newest first. Read-only."""
    days = days or config.get("days") or 30
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    box = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        box.login(config["email"], config["app_password"])
        box.select("INBOX", readonly=True)
        status, data = box.search(None, f'(SINCE "{since}")')
        if status != "OK":
            return []
        ids = data[0].split()
        ids = ids[-limit * 3:]  # headers are cheap; bodies are fetched only for hits
        found: list[dict] = []
        for uid in reversed(ids):
            status, head = box.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            if status != "OK" or not head or not isinstance(head[0], tuple):
                continue
            headers = email.message_from_bytes(head[0][1])
            sender = _decode(headers.get("From"))
            subject = _decode(headers.get("Subject"))
            if not _interesting(sender, subject):
                continue
            status, full = box.fetch(uid, "(BODY.PEEK[])")
            if status != "OK" or not full or not isinstance(full[0], tuple):
                continue
            message = email.message_from_bytes(full[0][1])
            try:
                when = email.utils.parsedate_to_datetime(headers.get("Date"))
                when_iso = when.astimezone().isoformat(timespec="minutes")
            except Exception:
                when_iso = ""
            body = _body_text(message)
            found.append({
                "id": (headers.get("Message-ID") or uid.decode()).strip(),
                "date": when_iso,
                "from": sender,
                "subject": subject,
                "snippet": body[:300],
                "body": body,
            })
            if len(found) >= limit:
                break
        return found
    finally:
        try:
            box.logout()
        except Exception:
            pass


def sync(applications: list[dict], days: int | None = None) -> dict:
    """Fetch, classify, match, store. Returns the store."""
    config = load_config()
    messages = fetch(config, days=days)
    store = load_store()
    known = {m.get("id"): m for m in store["emails"]}
    for message in messages:
        entry = {
            "id": message["id"],
            "date": message["date"],
            "from": message["from"],
            "subject": message["subject"],
            "snippet": message["snippet"],
            "kind": classify(message["subject"], message["body"]),
            "jobs": match_applications(message, applications),
        }
        known[entry["id"]] = entry
    emails = sorted(known.values(), key=lambda m: m.get("date") or "", reverse=True)
    store = {"synced_at": datetime.now().isoformat(timespec="seconds"), "emails": emails,
             "fetched": len(messages)}
    save_store(store)
    log.info("Gmail: %d job-related message(s) read, %d matched to applications",
             len(messages), sum(1 for m in emails if m.get("jobs")))
    return store


def per_application(store: dict | None = None) -> dict[str, dict]:
    """{job_id: {"kind": ..., "emails": [...]}} - the strongest signal wins."""
    store = store or load_store()
    out: dict[str, dict] = {}
    for message in store.get("emails") or []:
        for job_id in message.get("jobs") or []:
            slot = out.setdefault(job_id, {"kind": None, "emails": []})
            slot["emails"].append({k: message.get(k) for k in ("date", "from", "subject", "snippet", "kind")})
            if slot["kind"] is None or KIND_RANK.get(message.get("kind"), 0) > KIND_RANK.get(slot["kind"], 0):
                slot["kind"] = message.get("kind")
    for slot in out.values():
        slot["emails"].sort(key=lambda m: m.get("date") or "", reverse=True)
        slot["label"] = KIND_LABELS.get(slot["kind"], "Reply")
    return out
