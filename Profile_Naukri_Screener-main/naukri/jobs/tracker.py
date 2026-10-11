"""One memory of every job you are done with - applied to, or thrown away - that
every search, report and apply pass asks before showing or sending anything.

    python -m naukri.jobs.tracker --status           what it remembers, and the sheet's state
    python -m naukri.jobs.tracker --sync             write new applications to the Google Sheet, read rows back
    python -m naukri.jobs.tracker --test-sheet       can the sheet be reached and written?
    python -m naukri.jobs.tracker --reject URL...    never show or apply to these again
    python -m naukri.jobs.tracker --check URL        is this job already applied / rejected, and why?

Where "done" comes from, all merged:
  * data/jobs/ledger.json and applications.jsonl   everything the agent applied to, on any board
  * data/jobs/rejected.json                         jobs you removed on the phone (Queue -> Remove,
                                                     Track -> hide) or with --reject
  * data/jobs/application_notes.json                 a status you set on the phone's Track tab
  * the Google Sheet (jobs.yaml `tracker_sheet`)     rows you add by hand count too: a link in the
                                                     sheet = applied, unless its Status says
                                                     rejected / deleted / skip

A job matches when its id matches (Naukri jobId, LinkedIn job id), when its link
matches (tracking parameters stripped), or - `tracker_match_title: true` - when the
same title is posted by the same company: the same opening on Naukri, LinkedIn and
the company's own site is one job, not three.

The sheet. One row per application: Date time | Job link | Title | Company | Board |
Status | Applied by | Resume sent | Match % | Contact details | Notes | Key. Written
through the Google Sheets API with a service account (a JSON key file; share the
sheet with its client_email as Editor). An API key alone can only READ a sheet that
is shared "anyone with the link"; set `api_key` for that and rows are read back but
nothing is written. Reports never wait for Google: they read the local copy
(data/jobs/tracker_sheet.json) that the last sync left.

    tracker_sheet:
      spreadsheet: https://docs.google.com/spreadsheets/d/<id>/edit     # or just the id
      worksheet: Applications                                           # tab name; created if missing
      credentials: data/google_service_account.json                     # service-account key file
      # api_key: AIza...                                                # read-only alternative
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("naukri.jobs.tracker")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"
LEDGER_PATH = JOBS_DIR / "ledger.json"
APPLICATIONS_PATH = JOBS_DIR / "applications.jsonl"
NOTES_PATH = JOBS_DIR / "application_notes.json"
REJECTED_PATH = JOBS_DIR / "rejected.json"
SHEET_CACHE = JOBS_DIR / "tracker_sheet.json"
TAILORED_DIR = JOBS_DIR / "tailored"
RUNS_DIR = Path(os.path.expanduser("~")) / "Documents" / "JobHunt"

HEADER = ["Date time", "Job link", "Title", "Company", "Board", "Status", "Applied by",
          "Resume sent", "Match %", "Contact details", "Notes", "Key"]
APPLIED_STATUSES = {"applied", "submitted", "interview", "interviewing", "offer", "shortlisted", "manual", "done", "yes"}
REJECTED_STATUSES = {"rejected", "deleted", "removed", "skip", "skipped", "no", "not interested", "ignore", "hide", "hidden"}
TRACKING_PARAMS = re.compile(r"[?&](utm_[^&]*|ref[^&]*|trk[^&]*|position=\d+|pageNum=\d+|refId=[^&]*|trackingId=[^&]*|"
                             r"applicationOrigin=[^&]*|src=[^&]*|sid=[^&]*|xp=[^&]*|px=[^&]*|gh_src=[^&]*|lever-source[^&]*|"
                             r"source=[^&]*|page=\d+|sortBy=[^&]*|currentJobId=[^&]*|originalSubdomain=[^&]*)")
LINKEDIN_ID = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*?-)?(\d{6,})")
NAUKRI_ID = re.compile(r"naukri\.com/.*?-(\d{9,})(?:[/?#]|$)")


# ----------------------------------------------------------------------------- normalising

def norm_text(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def norm_key(key: str | None) -> str:
    """One spelling for a job id: '123' and 'naukri:123' are the same Naukri job."""
    k = str(key or "").strip()
    if k.lower().startswith("naukri:"):
        k = k[7:]
    return k.lower()


def norm_url(url: str | None) -> str:
    u = (url or "").strip().split("#")[0]
    if not u:
        return ""
    u = TRACKING_PARAMS.sub("", u).rstrip("?&")
    u = re.sub(r"^https?://(www\.|in\.|[a-z]{2}\.)?", "", u.strip(), flags=re.I)
    return u.rstrip("/").lower()


def keys_from_url(url: str | None) -> list[str]:
    """The board ids a link carries, in the ledger's spelling."""
    out = []
    m = LINKEDIN_ID.search(url or "")
    if m:
        out.append(f"linkedin:{m.group(1)}")
    m = NAUKRI_ID.search(url or "")
    if m:
        out.append(m.group(1))
    return out


def board_of(url: str | None, key: str | None = None) -> str:
    k = str(key or "")
    u = (url or "").lower()
    if k.startswith("linkedin:") or "linkedin.com" in u:
        return "linkedin"
    if "naukri.com" in u or (k.isdigit() and k):
        return "naukri"
    return "company site / other board"


# ----------------------------------------------------------------------------- the memory

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _mtimes() -> tuple:
    out = []
    for p in (LEDGER_PATH, APPLICATIONS_PATH, NOTES_PATH, REJECTED_PATH, SHEET_CACHE):
        try:
            out.append(p.stat().st_mtime_ns)
        except OSError:
            out.append(0)
    return tuple(out)


class Memory:
    """Everything done, indexed three ways. Build with Memory.shared() - it reloads
    only when one of the files changed."""

    _shared: "Memory | None" = None
    _stamp: tuple = ()

    def __init__(self, match_title: bool | None = None):
        self.match_title = _match_title_setting() if match_title is None else match_title
        self.keys: dict[str, str] = {}      # norm key  -> reason
        self.urls: dict[str, str] = {}      # norm url  -> reason
        self.pairs: dict[tuple, str] = {}   # (company, title) -> reason
        self.counts = {"applied": 0, "rejected": 0, "sheet": 0, "notes": 0}
        self._load()

    @classmethod
    def shared(cls) -> "Memory":
        stamp = _mtimes()
        if cls._shared is None or stamp != cls._stamp:
            cls._shared, cls._stamp = cls(), stamp
        return cls._shared

    @classmethod
    def forget_shared(cls) -> None:
        cls._shared, cls._stamp = None, ()

    # -- loading
    def _add(self, reason: str, key=None, url=None, company=None, title=None) -> None:
        for k in [norm_key(key)] + [norm_key(x) for x in keys_from_url(url)]:
            if k and k not in self.keys:
                self.keys[k] = reason
        u = norm_url(url)
        if u and u not in self.urls:
            self.urls[u] = reason
        c, t = norm_text(company), norm_text(title)
        if len(c) >= 3 and len(t) >= 3 and (c, t) not in self.pairs:
            self.pairs[(c, t)] = reason

    def _load(self) -> None:
        for key, e in (_read_json(LEDGER_PATH, {}) or {}).items():
            if not isinstance(e, dict) or e.get("status") != "applied":
                continue
            self.counts["applied"] += 1
            self._add(f"applied {str(e.get('at', ''))[:10]} ({board_of(e.get('url'), key)})",
                      key=key, url=e.get("url"), company=e.get("company"), title=e.get("title"))
        if APPLICATIONS_PATH.exists():
            try:
                for line in APPLICATIONS_PATH.read_text(encoding="utf-8").splitlines():
                    if '"applied"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("status") != "applied" or e.get("dry_run"):
                        continue
                    self._add(f"applied {str(e.get('at', ''))[:10]} ({e.get('board') or 'board'})",
                              key=e.get("job_id"), url=e.get("url"), company=e.get("company"), title=e.get("title"))
            except OSError:
                pass
        for item in _read_json(REJECTED_PATH, []) or []:
            if isinstance(item, dict):
                self.counts["rejected"] += 1
                self._add(f"{item.get('why') or 'rejected'} {str(item.get('at', ''))[:10]}",
                          key=item.get("key"), url=item.get("url"), company=item.get("company"), title=item.get("title"))
        for job_id, note in (_read_json(NOTES_PATH, {}) or {}).items():
            if not isinstance(note, dict):
                continue
            status = norm_text(note.get("status"))
            if note.get("hidden") or status in REJECTED_STATUSES:
                self.counts["notes"] += 1
                self._add(f"hidden on the phone {str(note.get('updated', ''))[:10]}", key=job_id)
            elif status in APPLIED_STATUSES:
                self.counts["notes"] += 1
                self._add(f"marked {status} on the phone {str(note.get('updated', ''))[:10]}", key=job_id)
        cache = _read_json(SHEET_CACHE, {}) or {}
        for row in cache.get("rows") or []:
            if not isinstance(row, dict):
                continue
            link = row.get("Job link") or ""
            key = row.get("Key") or ""
            if not link and not key:
                continue
            status = norm_text(row.get("Status"))
            self.counts["sheet"] += 1
            what = "rejected" if status in REJECTED_STATUSES else "applied"
            by = norm_text(row.get("Applied by")) or "sheet"
            self._add(f"{what} per the sheet ({by}) {str(row.get('Date time', ''))[:16]}",
                      key=key, url=link, company=row.get("Company"), title=row.get("Title"))

    # -- asking
    def blocked(self, key=None, url=None, company=None, title=None) -> str | None:
        """Why this job must not be shown or applied to again, or None."""
        for k in [norm_key(key)] + [norm_key(x) for x in keys_from_url(url)]:
            if k and k in self.keys:
                return self.keys[k]
        u = norm_url(url)
        if u and u in self.urls:
            return self.urls[u]
        if self.match_title:
            c, t = norm_text(company), norm_text(title)
            if len(c) >= 3 and len(t) >= 3 and (c, t) in self.pairs:
                return self.pairs[(c, t)] + " - same title at the same company"
        return None

    def filter(self, items, key=lambda it: None, url=lambda it: None, company=lambda it: None, title=lambda it: None,
               log_as: str | None = None) -> list:
        kept, dropped = [], 0
        for it in items:
            if self.blocked(key=key(it), url=url(it), company=company(it), title=title(it)):
                dropped += 1
            else:
                kept.append(it)
        if dropped and log_as:
            log.info("%s: %d posting(s) left out - already applied to or removed (tracker)", log_as, dropped)
        return kept


def _match_title_setting() -> bool:
    try:
        from . import config as config_mod
        return bool(config_mod.load().get("tracker_match_title", True))
    except Exception:  # noqa: BLE001 - no jobs.yaml: the default
        return True


# ----------------------------------------------------------------------------- rejecting

def reject(items: list[dict], why: str) -> int:
    """Remember these as thrown away: {key?, url?, company?, title?} each. Never shown or applied to again."""
    rows = _read_json(REJECTED_PATH, []) or []
    have = {(norm_key(r.get("key")), norm_url(r.get("url"))) for r in rows if isinstance(r, dict)}
    added = 0
    for it in items:
        key, url = norm_key(it.get("key")), norm_url(it.get("url"))
        if not key and not url and not (it.get("company") and it.get("title")):
            continue
        if (key, url) in have:
            continue
        have.add((key, url))
        rows.append({"key": it.get("key") or "", "url": it.get("url") or "", "company": it.get("company") or "",
                     "title": it.get("title") or "", "why": why, "at": datetime.now().isoformat(timespec="seconds")})
        added += 1
    if added:
        REJECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = REJECTED_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(REJECTED_PATH)
        Memory.forget_shared()
        log.info("tracker: %d job(s) marked '%s' - never shown or applied to again", added, why)
    return added


# ----------------------------------------------------------------------------- the Google Sheet

class SheetError(RuntimeError):
    pass


def sheet_settings(config: dict | None = None) -> dict:
    """jobs.yaml `tracker_sheet`, with TRACKER_SHEET / TRACKER_SHEET_CREDENTIALS / TRACKER_SHEET_API_KEY
    from the environment on top."""
    cfg = dict((config or {}).get("tracker_sheet") or {}) if config is not None else {}
    if config is None:
        try:
            from . import config as config_mod
            cfg = dict(config_mod.load().get("tracker_sheet") or {})
        except Exception:  # noqa: BLE001
            cfg = {}
    for env, key in (("TRACKER_SHEET", "spreadsheet"), ("TRACKER_SHEET_CREDENTIALS", "credentials"),
                     ("TRACKER_SHEET_API_KEY", "api_key"), ("TRACKER_SHEET_WORKSHEET", "worksheet")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    cfg.setdefault("worksheet", "Applications")
    return cfg


def spreadsheet_id(value: str) -> str:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value or "")
    return m.group(1) if m else (value or "").strip()


class Sheet:
    """The Sheets API v4 with a service account (read + write) or an API key (read only)."""

    def __init__(self, cfg: dict):
        self.id = spreadsheet_id(cfg.get("spreadsheet") or "")
        self.tab = cfg.get("worksheet") or "Applications"
        self.api_key = (cfg.get("api_key") or "").strip()
        cred = cfg.get("credentials") or ""
        self.cred_path = Path(os.path.expanduser(cred)) if cred else None
        if self.cred_path and not self.cred_path.is_absolute():
            self.cred_path = ROOT / self.cred_path
        self._token = None
        self._token_until = 0.0
        if not self.id:
            raise SheetError("tracker_sheet.spreadsheet is not set in jobs.yaml")
        if not (self.cred_path and self.cred_path.exists()) and not self.api_key:
            raise SheetError("tracker_sheet needs `credentials` (a service-account JSON file) to write, "
                             "or `api_key` to read only")

    @property
    def can_write(self) -> bool:
        return bool(self.cred_path and self.cred_path.exists())

    # -- auth
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_until - 60:
            return self._token
        import requests
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        sa = json.loads(self.cred_path.read_text(encoding="utf-8"))
        now = int(time.time())
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")  # noqa: E731
        header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claim = b64(json.dumps({"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
                                "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}).encode())
        key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
        sig = key.sign(header + b"." + claim, padding.PKCS1v15(), hashes.SHA256())
        assertion = (header + b"." + claim + b"." + b64(sig)).decode()
        r = requests.post("https://oauth2.googleapis.com/token", timeout=20,
                          data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
        if r.status_code != 200:
            raise SheetError(f"Google token: HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        self._token, self._token_until = data["access_token"], time.time() + int(data.get("expires_in") or 3600)
        return self._token

    def _call(self, method: str, path: str, **kw):
        import requests
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{self.id}{path}"
        headers = {}
        params = dict(kw.pop("params", {}) or {})
        if self.can_write:
            headers["Authorization"] = "Bearer " + self._access_token()
        else:
            params["key"] = self.api_key
        r = requests.request(method, url, headers=headers, params=params, timeout=30, **kw)
        if r.status_code >= 400:
            hint = ""
            if r.status_code == 403 and self.can_write:
                hint = " - share the sheet with the service account's client_email as Editor"
            if r.status_code == 403 and not self.can_write:
                hint = " - an API key can only read a sheet shared 'anyone with the link'; writing needs a service account"
            raise SheetError(f"Sheets API {method} {path}: HTTP {r.status_code} {r.text[:200]}{hint}")
        return r.json() if r.text else {}

    # -- reading / writing
    def tabs(self) -> list[str]:
        meta = self._call("GET", "", params={"fields": "sheets.properties.title"})
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def ensure_tab(self) -> None:
        if self.tab in self.tabs():
            return
        if not self.can_write:
            raise SheetError(f"worksheet '{self.tab}' does not exist (and an API key cannot create it)")
        self._call("POST", ":batchUpdate", json={"requests": [{"addSheet": {"properties": {"title": self.tab}}}]})

    def rows(self) -> tuple[list[str], list[dict]]:
        """(header, rows as dicts keyed by the header)."""
        data = self._call("GET", f"/values/{self._range('A1:Z')}", params={"majorDimension": "ROWS"})
        values = data.get("values") or []
        if not values:
            return [], []
        header = [str(h).strip() for h in values[0]]
        out = []
        for raw in values[1:]:
            if not any(str(c).strip() for c in raw):
                continue
            row = {header[i]: (raw[i] if i < len(raw) else "") for i in range(len(header)) if header[i]}
            out.append(row)
        return header, out

    def ensure_header(self) -> list[str]:
        header, _rows = self.rows()
        if header:
            return header
        self._call("PUT", f"/values/{self._range('A1')}", params={"valueInputOption": "RAW"},
                   json={"range": self._range("A1"), "majorDimension": "ROWS", "values": [HEADER]})
        return list(HEADER)

    def append(self, rows: list[list]) -> int:
        if not rows:
            return 0
        self._call("POST", f"/values/{self._range('A1')}:append",
                   params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                   json={"range": self._range("A1"), "majorDimension": "ROWS", "values": rows})
        return len(rows)

    def _range(self, cells: str) -> str:
        from urllib.parse import quote
        return quote(f"'{self.tab}'!{cells}", safe="!:'")


# ----------------------------------------------------------------------------- what goes in a row

def _resume_sent(entry: dict) -> str:
    """Which file the employer got: the tailored PDF for that job, else what the board holds."""
    note = str(entry.get("note") or "")
    board = str(entry.get("board") or "")
    if "tailored resume" in note:
        day = str(entry.get("at", ""))[:10].replace("-", "")
        slug = re.sub(r"[^a-z0-9]+", "-", f"{entry.get('company', '')}-{entry.get('title', '')}".lower()).strip("-")[:60]
        for p in sorted(TAILORED_DIR.glob(f"{day}-{slug}*.pdf"), reverse=True):
            return f"tailored PDF: {p.name}"
        return "tailored PDF (data/jobs/tailored)"
    if "generic resume" in note:
        return "generic PDF (current.pdf)"
    if board == "linkedin":
        return "LinkedIn profile resume"
    if board == "naukri":
        return "Naukri profile resume"
    return "generic PDF (current.pdf)"


def _match_pct(entry: dict) -> str:
    m = re.search(r"(\d+)% of the job's skills", str(entry.get("note") or ""))
    return m.group(1) if m else ""


_CONTACTS: dict[str, str] | None = None


def _contacts_for(company: str) -> str:
    """Recruiters / hiring managers the worldwide search found for this company (contacts.json of recent runs)."""
    global _CONTACTS
    if _CONTACTS is None:
        _CONTACTS = {}
        try:
            paths = sorted(RUNS_DIR.glob("*/contacts.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]
        except OSError:
            paths = []
        for p in paths:
            data = _read_json(p, {})
            if not isinstance(data, dict):
                continue
            for name, found in data.items():
                k = norm_text(name)
                if not k or k in _CONTACTS:
                    continue
                people = found.get("people") if isinstance(found, dict) else found
                bits = []
                for person in (people or [])[:4] if isinstance(people, list) else []:
                    if isinstance(person, dict):
                        bits.append(" ".join(str(person.get(f) or "") for f in ("name", "title", "email", "linkedin", "url")).strip())
                    elif person:
                        bits.append(str(person))
                text = "; ".join(b for b in bits if b)
                if text:
                    _CONTACTS[k] = text[:300]
    return _CONTACTS.get(norm_text(company), "")


def application_rows(since_ids: set[str]) -> tuple[list[list], list[str]]:
    """Rows for every real application not yet on the sheet, oldest first, and their ids."""
    rows, ids = [], []
    if not APPLICATIONS_PATH.exists():
        return rows, ids
    for line in APPLICATIONS_PATH.read_text(encoding="utf-8").splitlines():
        if '"applied"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("status") != "applied" or e.get("dry_run"):
            continue
        rid = f"{e.get('at', '')}|{e.get('job_id', '')}"
        if rid in since_ids:
            continue
        key = str(e.get("job_id") or "")
        rows.append([str(e.get("at", "")).replace("T", " "), e.get("url") or "", e.get("title") or "", e.get("company") or "",
                     e.get("board") or board_of(e.get("url"), key), "applied",
                     "auto (%s)" % (e.get("project") or "naukri"), _resume_sent(e), _match_pct(e),
                     _contacts_for(e.get("company") or ""), str(e.get("note") or "")[:300], key])
        ids.append(rid)
    return rows, ids


def sync_sheet(config: dict | None = None, budget_s: float = 40.0) -> dict:
    """Push new applications to the sheet, pull every row back into the local copy.
    Quiet when no sheet is configured. Returns {pushed, pulled, note}."""
    cfg = sheet_settings(config)
    if not cfg.get("spreadsheet"):
        return {"pushed": 0, "pulled": 0, "note": "no tracker_sheet in jobs.yaml"}
    t0 = time.time()
    state = _read_json(SHEET_CACHE, {}) or {}
    pushed_ids = set(state.get("pushed") or [])
    result = {"pushed": 0, "pulled": 0, "note": ""}
    try:
        sheet = Sheet(cfg)
        sheet.ensure_tab()
        if sheet.can_write:
            sheet.ensure_header()
            rows, ids = application_rows(pushed_ids)
            # oldest first, in chunks, so a slow network still lands something
            for i in range(0, len(rows), 200):
                if time.time() - t0 > budget_s:
                    result["note"] = "time budget used; the rest goes next time"
                    break
                sheet.append(rows[i:i + 200])
                pushed_ids.update(ids[i:i + 200])
                result["pushed"] += len(rows[i:i + 200])
        _header, pulled = sheet.rows()
        state.update({"rows": pulled, "pulled_at": datetime.now().isoformat(timespec="seconds"),
                      "pushed": sorted(pushed_ids), "spreadsheet": sheet.id, "worksheet": sheet.tab,
                      "can_write": sheet.can_write, "error": ""})
        result["pulled"] = len(pulled)
        if not sheet.can_write:
            result["note"] = "read-only (api_key): rows are read back, nothing is written"
    except SheetError as exc:
        state["error"] = f"{datetime.now().isoformat(timespec='seconds')} {exc}"
        state["pushed"] = sorted(pushed_ids)
        result["note"] = str(exc)
        log.warning("tracker sheet: %s", exc)
    except Exception as exc:  # noqa: BLE001 - network, JSON, anything: the local memory still works
        state["error"] = f"{datetime.now().isoformat(timespec='seconds')} {exc}"
        state["pushed"] = sorted(pushed_ids)
        result["note"] = str(exc)
        log.warning("tracker sheet: %s", exc)
    SHEET_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SHEET_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SHEET_CACHE)
    Memory.forget_shared()
    if result["pushed"] or result["pulled"]:
        log.info("tracker sheet: %d application(s) written, %d row(s) read back%s",
                 result["pushed"], result["pulled"], f" ({result['note']})" if result["note"] else "")
    return result


# ----------------------------------------------------------------------------- cli

def status_text() -> str:
    mem = Memory.shared()
    state = _read_json(SHEET_CACHE, {}) or {}
    cfg = sheet_settings()
    lines = [
        f"applied (ledger + applications log): {mem.counts['applied']}",
        f"rejected / removed on the phone:     {mem.counts['rejected']} (+{mem.counts['notes']} from Track statuses)",
        f"rows from the sheet:                 {mem.counts['sheet']}",
        f"ids / links / company+title indexed: {len(mem.keys)} / {len(mem.urls)} / {len(mem.pairs)}",
        f"same title at the same company counts as the same job: {'yes' if mem.match_title else 'no'}",
        "",
    ]
    if cfg.get("spreadsheet"):
        lines += [f"sheet: {spreadsheet_id(cfg['spreadsheet'])} tab '{cfg.get('worksheet')}' "
                  f"({'service account: ' + str(cfg.get('credentials')) if cfg.get('credentials') else 'api_key (read-only)'})",
                  f"last sync: {state.get('pulled_at') or 'never'}; rows pushed so far: {len(state.get('pushed') or [])}"]
        if state.get("error"):
            lines.append(f"last error: {state['error']}")
    else:
        lines.append("sheet: not set up - add tracker_sheet: to jobs.yaml (see this module's docstring)")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sync", action="store_true", help="write new applications to the sheet and read rows back")
    ap.add_argument("--test-sheet", action="store_true", help="reach the sheet, list its tabs, write nothing")
    ap.add_argument("--reject", nargs="+", metavar="URL", help="never show or apply to these links again")
    ap.add_argument("--check", metavar="URL", help="is this link already applied to / rejected?")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.reject:
        reject([{"url": u} for u in args.reject], "rejected by you")
    if args.check:
        why = Memory.shared().blocked(url=args.check)
        print(why or "not seen before - would be shown and applied to")
    if args.test_sheet:
        cfg = sheet_settings()
        try:
            s = Sheet(cfg)
            print(f"spreadsheet {s.id}: tabs {s.tabs()}; write access: {'yes' if s.can_write else 'no (api_key)'}")
        except SheetError as exc:
            print(f"sheet: {exc}")
            return 1
    if args.sync:
        print(json.dumps(sync_sheet(), ensure_ascii=False))
    if args.status or not any((args.reject, args.check, args.test_sheet, args.sync)):
        print(status_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
