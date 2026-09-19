"""Apply on a company's own careers site - unless it wants a login.

Used for every posting whose apply button leaves the board: Naukri's "Apply on
company site", LinkedIn's plain "Apply", and the worldwide search's postings
from other boards and career pages. One attempt per posting:

    1. From a Naukri / LinkedIn job page, click the offsite Apply button and
       follow the tab it opens. From any other URL, open it and click its
       Apply button if the form is not already on the page.
    2. Stop at a wall. A visible password box, "sign in / create an account to
       apply", a login URL, or a board known to need its own account
       -> "login-required". A visible CAPTCHA -> "captcha". Nothing is ever
       typed into a login form and no CAPTCHA is attempted.
    3. Fill the form from facts you gave: name, email, phone, links, location
       and the resume file (jobs.yaml `applicant:`, else your resume and
       data/profile.json), screening questions through answers.resolve() (the
       same rules and answer bank the Naukri and LinkedIn walkers use),
       "prefer not to say" on voluntary diversity questions, and the required
       privacy / consent box.
    4. A required field it cannot answer from those facts -> "career-incomplete"
       (nothing submitted; the question is in the note). Otherwise press
       Submit, follow up to five form pages, and look for a thank-you page:
       "submitted", or "career-unconfirmed" when none appears.

A screenshot of the last state is saved in data/jobs/career_shots/ for every
attempt, so you can see what was sent or where it stopped.

    python -m naukri.jobs.career_apply <url> [--submit] [--show]   try one posting
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("naukri.jobs.career_apply")

ROOT = Path(__file__).resolve().parent.parent.parent
SHOTS = ROOT / "data" / "jobs" / "career_shots"

# Every status apply_from_page() returns (callers record these themselves).
STATUSES = {"submitted", "login-required", "captcha", "no-form", "career-incomplete",
            "career-unconfirmed", "career-error"}

# Ledger notes for company-site attempts start with this, so a posting is tried
# on its careers site once and then left alone.
TRIED = "company site: "

# Boards whose apply always needs an account there - not worth opening.
LOGIN_HOSTS = ("wellfound.com", "angel.co", "xing.com", "seek.com", "jobsdb.com", "jobstreet.com",
               "indeed.", "glassdoor.", "infojobs.net", "instahyre.com", "monster.", "foundit.in",
               "naukri.com/mnjuser", "linkedin.com/login", "simplyhired.")

# Button texts, in the languages of the boards the search covers. Loose on
# purpose ("Apply for this job at Acme", "Jetzt bewerben", "応募する"), with the
# look-alikes that are not an application ruled out by NOT_ACTION.
APPLY_TEXT = re.compile(r"^\W*(apply|easy apply|i'?m interested|start (your |an )?application|(jetzt )?bewerben|"
                        r"postular|postúlate|inscr[ií]b|solliciteer|hae\b|haku|candidat|応募|エントリー|สมัคร)"
                        r".{0,45}$", re.I)
SUBMIT_TEXT = re.compile(r"^\W*(submit|send|apply|finish|complete (my |your )?application|bewerbung|absenden|"
                         r"enviar|envoyer|verzenden|verstuur|lähetä|送信|応募する|ส่ง)"
                         r".{0,30}$", re.I)
NOT_ACTION = re.compile(r"\b(filters?|alerts?|later|save (for|job)|similar|share|sign ?(in|up)|log ?in|register|"
                        r"with (linkedin|indeed|google|seek|xing)|go back|cancel|newsletter)\b", re.I)
NEXT_TEXT = re.compile(r"^\s*(next|continue|save (and|&) continue|proceed)\s*[›>→]?\s*$", re.I)
THANKS = re.compile(r"thank(s| you) for (applying|your (application|interest))|application (has been |was )?"
                    r"(received|submitted|sent|complete)|we('ve| have) received your application|"
                    r"successfully (applied|submitted)|your application is on its way", re.I)
LOGIN_WALL = re.compile(r"(sign|log)\s*-?\s*in to (apply|continue|your account)|create (an |your )?account to (apply|continue)|"
                        r"please (sign|log)\s*-?\s*in|register to apply|already have an account\?", re.I)
LOGIN_URL = re.compile(r"/(login|log-in|signin|sign-in|sign_in|auth|sso|oauth|account/(create|register)|register)\b", re.I)

# Field meaning from its label / name / placeholder. First match wins.
FIELD_RULES: list[tuple[str, str]] = [
    ("first_name", r"first\s*name|given\s*name|fname|first_name|firstname"),
    ("last_name", r"last\s*name|surname|family\s*name|lname|last_name|lastname"),
    ("email", r"e-?mail"),
    ("phone", r"phone|mobile|contact\s*number|telephone|\btel\b"),
    ("linkedin", r"linkedin"),
    ("github", r"github"),
    ("website", r"website|portfolio|personal\s*(site|url|page)|\bblog\b|other\s*(url|link)"),
    ("resume", r"resume|\bcv\b|curriculum"),
    ("cover_letter", r"cover\s*letter|motivation"),
    ("full_name", r"^\s*(full\s*|your\s*|legal\s*)?name\s*\*?\s*$|full\s*name|candidate\s*name"),
    ("current_company", r"current\s*(company|employer)|present\s*employer|company\s*name"),
    ("current_title", r"current\s*(job\s*)?(title|role|position|designation)"),
    ("city", r"^\s*city|current\s*city|town"),
    ("location", r"location|where\s+(are\s+you|do\s+you)\s+(based|live)|address"),
    ("country", r"^\s*country"),
    ("hear", r"how\s+did\s+you\s+(hear|find|learn)|source|referr?al\s*source"),
    ("eeo", r"gender|race|ethnic|veteran|disabilit|sexual\s*orientation|pronoun|hispanic|latino"),
    ("consent", r"privacy|consent|i\s+agree|terms|acknowledg|data\s*(protection|processing)|gdpr"),
]
EEO = re.compile(dict(FIELD_RULES)["eeo"], re.I)
PLACEHOLDER = re.compile(r"^\s*(select|choose|please|pick|--|—|-\s*$)", re.I)
DECLINE = re.compile(r"(decline|prefer not|do not wish|don'?t wish|not (to )?(say|disclose|specify)|rather not)", re.I)

SCAN_JS = r"""
(() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return (r.width > 1 || r.height > 1 || e.type === 'file') && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = e => (e ? (e.innerText || e.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const labelOf = e => {
    let t = '';
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) t = txt(l); }
    if (!t && e.closest('label')) t = txt(e.closest('label'));
    if (!t && e.getAttribute('aria-labelledby')) t = e.getAttribute('aria-labelledby').split(' ').map(i => txt(document.getElementById(i))).join(' ');
    if (!t) t = e.getAttribute('aria-label') || '';
    if (!t) { const f = e.closest('fieldset'); if (f && f.querySelector('legend')) t = txt(f.querySelector('legend')); }
    if (!t) { let p = e.parentElement; for (let i = 0; i < 3 && p && !t; i++, p = p.parentElement) {
      const c = p.querySelector('label, legend, .label, [class*=label], [class*=question]'); if (c && !c.contains(e)) t = txt(c); } }
    return t.slice(0, 300);
  };
  const out = []; let n = 0;
  document.querySelectorAll('input, textarea, select').forEach(e => {
    const type = (e.type || e.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) return;
    if (type !== 'file' && !vis(e)) return;
    if (e.disabled || e.readOnly) return;
    const idx = String(n++); e.setAttribute('data-ca', idx);
    let group = '', optionLabel = '';
    if (type === 'radio' || type === 'checkbox') {
      group = e.name || ''; optionLabel = (e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]')) ? txt(document.querySelector('label[for="' + CSS.escape(e.id) + '"]')) : txt(e.closest('label'));
    }
    const fs = e.closest('fieldset'), legend = fs && fs.querySelector('legend') ? txt(fs.querySelector('legend')) : '';
    out.push({ idx, tag: e.tagName.toLowerCase(), type, name: e.name || '', id: e.id || '',
      placeholder: e.placeholder || '', autocomplete: e.getAttribute('autocomplete') || '',
      label: labelOf(e), legend, group, optionLabel, value: e.value || '', checked: !!e.checked,
      required: e.required || e.getAttribute('aria-required') === 'true' || /\*\s*$/.test(labelOf(e)),
      options: e.tagName === 'SELECT' ? Array.from(e.options).map(o => o.text.trim()).filter(Boolean) : [],
      selectedText: e.tagName === 'SELECT' && e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : '',
      password: type === 'password' });
  });
  return out;
})()
"""


# ------------------------------------------------------------------ applicant

def _resume_path(config: dict) -> str | None:
    app = config.get("applicant") or {}
    for cand in [app.get("resume"), os.environ.get("APPLY_RESUME")]:
        if cand and os.path.exists(os.path.expanduser(str(cand))):
            return os.path.abspath(os.path.expanduser(str(cand)))
    # The resume the worldwide search last scored against.
    runs = Path(os.path.expanduser("~")) / "Documents" / "JobHunt"
    try:
        metas = sorted(runs.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        for meta in metas:
            path = (json.loads(meta.read_text(encoding="utf-8")).get("meta") or {}).get("resume_path")
            if path and os.path.exists(path):
                return path
    except OSError:
        pass
    for pattern in ("*.pdf", "*.docx"):
        found = sorted((ROOT / "resume").glob(pattern))
        if found:
            return str(found[0])
    return None


def _resume_text(path: str | None) -> str:
    if not path:
        return ""
    try:
        if path.lower().endswith(".pdf"):
            from pypdf import PdfReader
            return " ".join((p.extract_text() or "") for p in PdfReader(path).pages[:3])
        if path.lower().endswith(".docx"):
            import docx
            return " ".join(p.text for p in docx.Document(path).paragraphs)
    except Exception as exc:  # noqa: BLE001 - a missing parser only costs the parsed fields
        log.debug("resume text unreadable: %s", exc)
    return ""


def applicant(profile: dict, config: dict) -> dict:
    """Your details for application forms: jobs.yaml `applicant:` wins, then
    the resume's header, then data/profile.json."""
    app = {k: v for k, v in (config.get("applicant") or {}).items() if v not in (None, "")}
    resume = _resume_path(config)
    text = _resume_text(resume)
    email = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", text)
    phone = re.search(r"\+?\d[\d \-()]{8,}\d", text)
    linkedin = re.search(r"linkedin\.com/in/[\w\-%]+", text, re.I)
    github = re.search(r"github\.com/[\w\-]+", text, re.I)
    name = app.get("name") or (profile.get("name") or "").strip()
    name = " ".join(w[:1].upper() + w[1:] for w in name.split())
    location = app.get("location") or (profile.get("location") or "").replace(", INDIA", ", India")
    stated_phone = str((config.get("answers") or {}).get("phone") or "")
    who = {
        "name": name,
        "first_name": app.get("first_name") or (name.split()[0] if name else ""),
        "last_name": app.get("last_name") or (" ".join(name.split()[1:]) if len(name.split()) > 1 else ""),
        "email": app.get("email") or (email.group(0) if email else ""),
        "phone": str(app.get("phone") or (phone.group(0).strip() if phone else "") or stated_phone),
        "linkedin": app.get("linkedin") or ("https://www." + linkedin.group(0) if linkedin else ""),
        "github": app.get("github") or ("https://" + github.group(0) if github else ""),
        "website": app.get("website") or "",
        "location": location,
        "city": app.get("city") or location.split(",")[0].strip(),
        "country": app.get("country") or (location.split(",")[-1].strip() if "," in location else ""),
        "current_company": app.get("current_company") or "",
        "current_title": app.get("current_title") or "",
        "resume": resume,
        "hear": app.get("how_did_you_hear") or "Job board",
        "cover_letter": app.get("cover_letter") or "",
    }
    designation = profile.get("current_designation") or ""
    m = re.match(r"(.+?)\s+at\s+(.+)", designation)
    if m:
        who["current_title"] = who["current_title"] or m.group(1).strip()
        who["current_company"] = who["current_company"] or m.group(2).strip()
    return who


def missing_details(who: dict) -> list[str]:
    return [k for k in ("first_name", "email", "phone", "resume") if not who.get(k)]


# ------------------------------------------------------------------ page helpers

def _frames(page):
    return [page.main_frame] + [f for f in page.frames if f != page.main_frame]


def _visible(locator, timeout=600) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible(timeout=timeout)
    except Exception:
        return False


def _body(page) -> str:
    out = []
    for frame in _frames(page):
        try:
            out.append(frame.locator("body").inner_text(timeout=3000))
        except Exception:
            continue
    return " ".join(out)


def login_wall(page) -> str | None:
    if LOGIN_URL.search(page.url or "") and not re.search(r"/apply", page.url or "", re.I):
        return "the site sends you to a login page"
    for frame in _frames(page):
        try:
            if _visible(frame.locator("input[type=password]")):
                return "the site asks for a login / account"
        except Exception:
            continue
    body = _body(page)
    m = LOGIN_WALL.search(body)
    if m:
        return f"the site says '{m.group(0)}'"
    return None


def captcha(page) -> bool:
    for sel in ("iframe[src*='recaptcha/api2/anchor']", "iframe[src*='recaptcha/api2/bframe']",
                "iframe[src*='hcaptcha.com']", "iframe[src*='challenges.cloudflare.com']", "iframe[title*='captcha' i]"):
        for frame in _frames(page):
            try:
                if _visible(frame.locator(sel), timeout=300):
                    return True
            except Exception:
                continue
    return False


def _click_text(target, pattern: re.Pattern, selector="button, a, input[type=submit], [role=button]") -> bool:
    """Click the first visible control whose text matches. `target` is a page (all its frames) or one frame."""
    for frame in (_frames(target) if hasattr(target, "main_frame") else [target]):
        try:
            items = frame.locator(selector)
            for i in range(min(items.count(), 150)):
                el = items.nth(i)
                try:
                    if not el.is_visible(timeout=200):
                        continue
                    text = el.inner_text(timeout=300) if el.evaluate("e => e.tagName") != "INPUT" else (el.get_attribute("value") or "")
                    text = re.sub(r"\s+", " ", text or "").strip()
                    if pattern.match(text) and not NOT_ACTION.search(text):
                        el.click(timeout=6000)
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _form_frame(page):
    """The frame holding the application form (Greenhouse and friends embed it) and its fields."""
    best, best_fields = None, []
    for frame in _frames(page):
        try:
            fields = frame.evaluate(SCAN_JS)
        except Exception:
            continue
        useful = [f for f in fields if f["type"] not in ("checkbox",) or f["required"]]
        if len(useful) > len(best_fields):
            best, best_fields = frame, fields
    return best, best_fields


# ------------------------------------------------------------------ filling

def _meaning(field: dict) -> str | None:
    text = " ".join([field["label"], field["name"], field["id"], field["placeholder"], field["autocomplete"]])
    auto = field["autocomplete"].lower()
    if auto in ("given-name",):
        return "first_name"
    if auto in ("family-name",):
        return "last_name"
    if auto == "email" or field["type"] == "email":
        return "email"
    if auto == "tel" or field["type"] == "tel":
        return "phone"
    if field["type"] == "file":
        return "cover_letter" if re.search(r"cover|motivation", text, re.I) else "resume"
    for meaning, pattern in FIELD_RULES:
        if re.search(pattern, field["label"] or "", re.I):
            return meaning
    for meaning, pattern in FIELD_RULES:
        if meaning in ("full_name",):
            continue
        if re.search(pattern, text, re.I):
            return meaning
    if re.fullmatch(r"\s*name\s*", field["name"] or "", re.I):
        return "full_name"
    return None


def _question(field: dict) -> str:
    return (field["legend"] or field["label"] or field["placeholder"] or field["name"]).strip(" *")


def _cover(who: dict, job: dict) -> str:
    if who.get("cover_letter"):
        return who["cover_letter"]
    title, company = job.get("title") or "this role", job.get("company") or "your team"
    return (f"Dear Hiring Team,\n\nI would like to apply for {title} at {company}. I am a "
            f"{who.get('current_title') or 'software engineer'}"
            f"{' at ' + who['current_company'] if who.get('current_company') else ''}; my resume is attached "
            f"and my profile is at {who.get('linkedin') or who.get('github') or ''}.\n\nKind regards,\n{who.get('name')}")


def fill_form(frame, fields: list[dict], who: dict, facts: dict, job: dict, capture: dict) -> tuple[int, list[str]]:
    """Fill what can be filled from facts. Returns (filled, unanswered required questions)."""
    from . import answers as answers_mod

    filled, blocked = 0, []
    groups: dict[str, list[dict]] = {}
    for f in fields:
        if f["type"] in ("radio", "checkbox") and f["group"]:
            groups.setdefault(f["group"], []).append(f)

    def loc(f):
        return frame.locator(f'[data-ca="{f["idx"]}"]')

    def record(q, a, src):
        capture.setdefault("answers", []).append({"question": q, "options": [], "answer": a, "source": src})

    done_groups = set()
    for f in fields:
        meaning = _meaning(f)
        q = _question(f)
        try:
            # ---- radio / checkbox groups
            if f["type"] in ("radio", "checkbox"):
                key = f["group"] or f["idx"]
                if key in done_groups:
                    continue
                done_groups.add(key)
                members = groups.get(f["group"], [f]) if f["group"] else [f]
                if any(m["checked"] for m in members):
                    continue
                q = _question(f) if f["legend"] else (f["label"] if len(members) == 1 else f["legend"] or f["label"])
                required = any(m["required"] for m in members)
                if f["type"] == "checkbox" and len(members) == 1:
                    if meaning == "consent" or (required and re.search(r"agree|consent|confirm|acknowledg|certify", q, re.I)):
                        loc(f).check(timeout=4000, force=True)
                        filled += 1
                        record(q, "checked", "consent")
                    elif required:
                        blocked.append(q)
                    continue
                options = [m["optionLabel"] or m["label"] for m in members]
                if meaning == "eeo" or EEO.search(q or ""):
                    pick = next((m for m in members if DECLINE.search(m["optionLabel"] or m["label"])), None)
                    if pick:
                        loc(pick).check(timeout=4000, force=True)
                        filled += 1
                    elif required:
                        blocked.append(q)
                    continue
                answer, why = answers_mod.resolve(q, options, facts)
                choice = answers_mod.choose_option(answer, options) if answer is not None else None
                if choice is None:
                    if required:
                        blocked.append(q)
                        capture.setdefault("question", q)
                        capture.setdefault("options", options)
                        capture.setdefault("why", why)
                    continue
                target = next(m for m in members if (m["optionLabel"] or m["label"]) == choice)
                loc(target).check(timeout=4000, force=True)
                filled += 1
                record(q, choice, why)
                continue

            if f["tag"] == "select":
                if f["value"] and f["selectedText"] and not PLACEHOLDER.match(f["selectedText"]):
                    continue
            elif f["value"]:
                continue

            # ---- files
            if f["type"] == "file":
                if meaning == "resume" and who.get("resume"):
                    loc(f).set_input_files(who["resume"], timeout=8000)
                    filled += 1
                elif f["required"] and meaning != "resume":
                    blocked.append(q or "file upload")
                continue

            # ---- plain values from your details
            value = None
            if meaning in ("first_name", "last_name", "email", "phone", "linkedin", "github", "website",
                           "current_company", "current_title", "city", "location", "country"):
                value = who.get(meaning) or None
                if meaning == "website" and not value:
                    value = who.get("github") or who.get("linkedin") or None
            elif meaning == "full_name":
                value = who.get("name")
            elif meaning == "hear":
                value = who.get("hear")
            elif meaning == "cover_letter" and f["tag"] == "textarea":
                value = _cover(who, job) if f["required"] else None
            elif meaning == "eeo" and f["tag"] == "select":
                pick = next((o for o in f["options"] if DECLINE.search(o)), None)
                if pick:
                    loc(f).select_option(label=pick, timeout=4000)
                    filled += 1
                elif f["required"]:
                    blocked.append(q)
                continue

            if f["tag"] == "select":
                options = [o for o in f["options"] if not PLACEHOLDER.match(o)]
                choice = None
                if value:
                    choice = next((o for o in options if o.lower() == str(value).lower()), None) or \
                        next((o for o in options if str(value).lower() in o.lower() or o.lower() in str(value).lower()), None)
                if choice is None and meaning not in ("country", "city", "location"):
                    answer, why = answers_mod.resolve(q, options, facts)
                    choice = answers_mod.choose_option(answer, options) if answer is not None else None
                if choice is None:
                    if f["required"]:
                        blocked.append(q)
                        capture.setdefault("question", q)
                        capture.setdefault("options", options)
                    continue
                loc(f).select_option(label=choice, timeout=4000)
                filled += 1
                record(q, choice, meaning or "answers")
                continue

            if value is None:
                answer, why = answers_mod.resolve(q, [], facts) if q else (None, "")
                if answer is None:
                    if f["required"]:
                        blocked.append(q or f["name"] or "a required field")
                        capture.setdefault("question", q)
                        capture.setdefault("why", why)
                    continue
                value = answer
                record(q, answer, why)
            loc(f).fill(str(value), timeout=5000)
            filled += 1
            # Autocomplete boxes (city pickers) want a pick from their list.
            if meaning in ("city", "location"):
                frame.wait_for_timeout(900)
                try:
                    option = frame.locator("[role=option]").first
                    if option.is_visible(timeout=700):
                        option.click(timeout=3000)
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001 - one odd widget should not sink the form
            log.debug("could not fill %r: %s", q, exc)
            if f.get("required"):
                blocked.append(q or "a required field")
    return filled, blocked


# ------------------------------------------------------------------ the attempt

def _shot(page, job: dict, suffix: str = "") -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^a-z0-9]+", "-", (job.get("company", "") + "-" + job.get("title", "")).lower())[:60].strip("-") or "posting"
    path = SHOTS / f"{time.strftime('%Y%m%d-%H%M')}-{key}{suffix}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
    except Exception:
        return ""
    return str(path)


LEAVE_LINKEDIN = re.compile(r"linkedin\.com/(safety/go|redir/|checkpoint/)", re.I)
CONTINUE_TEXT = re.compile(r"^\s*(continue|proceed|go to (site|company site|the site)|visit (site|website))\s*$", re.I)


def _leave_linkedin(page) -> None:
    """Get past LinkedIn's "you are leaving LinkedIn" page.

    Its URL carries the destination (`/safety/go/?url=...`), so that is opened
    directly; failing that, the page's Continue button is pressed.
    """
    from urllib.parse import parse_qs, unquote, urlparse
    try:
        url = page.url or ""
        if not LEAVE_LINKEDIN.search(url):
            return
        target = (parse_qs(urlparse(url).query).get("url") or [""])[0]
        if target.startswith("http"):
            page.goto(unquote(target), wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            return
        for el in page.locator("button, a").all()[:60]:
            txt = (el.inner_text(timeout=200) or "").strip()
            if CONTINUE_TEXT.match(txt) and el.is_visible():
                el.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                return
    except Exception:
        pass


def _follow_click(page, click) -> object:
    """Run click(); return the page the application continues on (a new tab if one opened)."""
    context = page.context
    before = len(context.pages)
    if not click():
        return None
    page.wait_for_timeout(3000)
    if len(context.pages) > before:
        new = context.pages[-1]
        try:
            new.wait_for_load_state("domcontentloaded", timeout=45000)
        except Exception:
            pass
        new.wait_for_timeout(2500)
        _leave_linkedin(new)
        return new
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    _leave_linkedin(page)
    return page


def apply_from_page(page, job: dict, who: dict, facts: dict, dry_run: bool = True,
                    capture: dict | None = None, offsite_click=None, prefill=None) -> tuple[str, str]:
    """Apply starting from `page`, which shows the posting.

    `offsite_click` is a callable that presses the board's own offsite button
    (Naukri / LinkedIn); without it the posting's own Apply button is used when
    the form is not on the page yet. `prefill(page) -> int` gets the form
    first when given (Simplify's autofill, see simplify.py); fill_form then
    only answers what it left empty. Returns (status, note); extra tabs opened
    here are closed before returning.
    """
    capture = capture if capture is not None else {}
    lacking = missing_details(who)
    if lacking and prefill is None:
        return "career-incomplete", f"set applicant.{', applicant.'.join(lacking)} in jobs.yaml"
    opened = set()
    current = page
    try:
        if offsite_click is not None:
            nxt = _follow_click(page, offsite_click)
            if nxt is None:
                return "career-error", "could not press the company-site Apply button"
            current = nxt
        if current is not page:
            opened.add(current)
        url = current.url or ""
        if any(h in url for h in LOGIN_HOSTS):
            host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            return "login-required", f"{host} needs its own account"

        total_filled = 0
        for step in range(6):
            wall = login_wall(current)
            if wall:
                _shot(current, job, "-login")
                return "login-required", wall
            if captcha(current):
                _shot(current, job, "-captcha")
                return "captcha", "the form has a CAPTCHA - apply by hand"
            frame, fields = _form_frame(current)
            fillable = [f for f in fields if f["type"] not in ("checkbox", "radio")]
            if len(fillable) < 2:
                if total_filled:
                    break               # submitted a page and no further form: check for a thank-you
                page_now = current
                nxt = _follow_click(current, lambda: _click_text(page_now, APPLY_TEXT))
                if nxt is None:
                    return "no-form", "no application form or Apply button found on the company page"
                if nxt is not current:
                    opened.add(nxt)
                current = nxt
                if any(h in (current.url or "") for h in LOGIN_HOSTS):
                    return "login-required", "the Apply button leads to a site that needs its own account"
                continue

            prefilled = 0
            if prefill is not None:
                try:
                    prefilled = int(prefill(current) or 0)
                except Exception as exc:  # noqa: BLE001 - Simplify is a helper, not a requirement
                    log.debug("prefill failed: %s", exc)
                frame, fields = _form_frame(current)     # rescan: values and pages may have changed
            filled, blocked = fill_form(frame, fields, who, facts, job, capture)
            total_filled += filled + prefilled
            if blocked:
                shot = _shot(current, job, "-incomplete")
                return "career-incomplete", f"cannot answer: {'; '.join(b[:60] for b in blocked[:3])} ({shot})"
            if dry_run:
                return "would-apply", f"{total_filled} field(s) filled; dry run ({_shot(current, job, '-dry')})"

            if not (_click_text(frame, SUBMIT_TEXT) or _click_text(current, SUBMIT_TEXT)):
                if not (_click_text(frame, NEXT_TEXT) or _click_text(current, NEXT_TEXT)):
                    try:
                        frame.locator("button[type=submit], input[type=submit]").first.click(timeout=5000)
                    except Exception:
                        return "career-incomplete", f"filled {total_filled} field(s) but found no Submit button ({_shot(current, job, '-nosubmit')})"
            current.wait_for_timeout(5000)
            if captcha(current):
                _shot(current, job, "-captcha")
                return "captcha", "a CAPTCHA appeared on submit - apply by hand"
            body = _body(current)
            if THANKS.search(body) or re.search(r"thank|confirm|success|submitted", current.url or "", re.I):
                return "submitted", f"{total_filled} field(s) filled and submitted ({_shot(current, job, '-done')})"
            try:
                invalid = frame.locator("[aria-invalid=true]:visible, .error:visible, .field-error:visible, [class*=error-message]:visible").count()
            except Exception:
                invalid = 0
            if invalid:
                return "career-incomplete", f"the form rejected some answers ({_shot(current, job, '-errors')})"
            # Otherwise a multi-page form moved on: fill the next page.
        body = _body(current)
        if THANKS.search(body):
            return "submitted", f"{total_filled} field(s) filled and submitted ({_shot(current, job, '-done')})"
        return "career-unconfirmed", f"pressed Submit, no confirmation seen ({_shot(current, job, '-after')})"
    except Exception as exc:  # noqa: BLE001
        return "career-error", str(exc)[:160]
    finally:
        for extra in opened:
            try:
                if extra is not page:
                    extra.close()
            except Exception:
                pass


def transient(status: str, note: str) -> bool:
    """A failure worth another go next run (network down, a timeout) - not recorded as tried."""
    return status == "career-error" and bool(re.search(r"net::ERR|Timeout|timed out|Target closed|has been closed", note or "", re.I))


def ledger_status(status: str) -> str:
    """How an outcome is stored: a submission counts as applied; everything
    else is finished on this site ("offsite") so it is not retried every run."""
    return "applied" if status == "submitted" else "offsite"


def queue_status(status: str) -> str:
    return {"submitted": "submitted", "would-apply": "queued"}.get(status, "manual")


def main(argv=None) -> int:
    import argparse
    from playwright.sync_api import sync_playwright

    from . import answers as answers_mod, config as config_mod, questions
    from ..session import launch_browser, new_context

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--submit", action="store_true", help="really submit (default: fill only)")
    ap.add_argument("--show", action="store_true", help="visible browser")
    a = ap.parse_args(argv)
    profile = config_mod.load_profile()
    config = config_mod.load(profile=profile)
    facts = answers_mod.build_facts(profile, config)
    facts["_bank"] = questions.load_bank()
    who = applicant(profile, config)
    print("applicant:", {k: (v if k != "cover_letter" else "...") for k, v in who.items()})
    with sync_playwright() as p:
        browser = launch_browser(p, headless=not a.show, offscreen=False)
        page = new_context(browser, viewport={"width": 1366, "height": 900}).new_page()
        page.goto(a.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        print(apply_from_page(page, {"url": a.url}, who, facts, dry_run=not a.submit))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
