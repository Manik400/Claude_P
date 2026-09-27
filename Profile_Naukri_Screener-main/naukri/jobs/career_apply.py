"""Apply on a company's own careers site - unless it wants a login.

Used for every posting whose apply button leaves the board: Naukri's "Apply on
company site", LinkedIn's plain "Apply", and the worldwide search's postings
from other boards and career pages. One attempt per posting:

    1. From a Naukri / LinkedIn job page, click the offsite Apply button and
       follow the tab it opens. From any other URL, open it and click its
       Apply button if the form is not already on the page.
    2. Clear what covers the page: a cookie banner is declined ("Reject all" /
       "Necessary only", never "Accept"), a "get job alerts" pop-up is closed,
       and job-alert / newsletter / search boxes are never taken for the form.
       Then stop at a wall. A visible password box, "sign in / create an account to
       apply", a login URL, or a board known to need its own account
       -> "login-required". A visible CAPTCHA -> "captcha". Nothing is ever
       typed into a login form and no CAPTCHA is attempted.
    3. Fill the form from facts you gave: name, email, phone, links, location
       and the resume file (jobs.yaml `applicant:`, else your resume and
       data/profile.json), screening questions through answers.resolve() (the
       same rules and answer bank the Naukri and LinkedIn walkers use,
       including open questions written from your resume by the local model),
       "prefer not to say" on voluntary diversity questions, and the required
       privacy / consent box. Google Forms and other ARIA widgets (div radios,
       checkboxes, dropdowns) are filled as well as plain inputs.
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
import random
import re
import time
from pathlib import Path

from . import human, platform_switch

log = logging.getLogger("naukri.jobs.career_apply")

ROOT = Path(__file__).resolve().parent.parent.parent
SHOTS = ROOT / "data" / "jobs" / "career_shots"

# Every status apply_from_page() returns (callers record these themselves).
STATUSES = {"submitted", "login-required", "captcha", "no-form", "career-incomplete",
            "career-unconfirmed", "career-error", "closed", "platform-off"}

# A listing that no longer takes applications. Before this was checked, a closed
# LinkedIn / Naukri posting showed up as "no application form found - apply by hand".
CLOSED = re.compile(r"no longer accepting applications|(this |the )?(job|position|posting|vacancy|role|opening) "
                    r"(is |has )?(no longer (available|open|active)|(been )?(closed|filled|expired|removed))|"
                    r"job (has )?expired|(job|posting) you are looking for (is|has) expired|applications (are )?(now )?closed|this job is closed|"
                    r"stelle (ist )?(nicht mehr|bereits) (verfügbar|besetzt)|oferta (no disponible|cerrada|caducada)|"
                    r"募集(は)?終了|ประกาศนี้หมดอายุ", re.I)

# Hosted application systems, from the posting page to the form page itself.
# They need no account, and their form URLs are predictable.
ATS_FORM = [
    (re.compile(r"^(https?://jobs\.lever\.co/[^/?#]+/[0-9a-f-]{20,})/?(?:[?#].*)?$", re.I), r"\1/apply"),
    (re.compile(r"^(https?://jobs\.ashbyhq\.com/[^/?#]+/[0-9a-f-]{20,})/?(?:[?#].*)?$", re.I), r"\1/application"),
    (re.compile(r"^(https?://apply\.workable\.com/[^/?#]+/j/[0-9A-F]+)/?(?:[?#].*)?$", re.I), r"\1/apply/"),
    (re.compile(r"^(https?://[^/]+\.breezy\.hr/p/[^/?#]+)/?(?:[?#].*)?$", re.I), r"\1/apply"),
    (re.compile(r"^(https?://[^/]+\.recruitee\.com/o/[^/?#]+)/?(?:[?#].*)?$", re.I), r"\1/c/new"),
    (re.compile(r"^(https?://[^/]+\.teamtailor\.com/jobs/[^/?#]+)/?(?:[?#].*)?$", re.I), r"\1/applications/new"),
    (re.compile(r"^(https?://jobs\.jobvite\.com/[^/?#]+/job/[^/?#]+)/?(?:[?#].*)?$", re.I), r"\1/apply"),
]
# Application systems that always make you create an account first.
ACCOUNT_ATS = ("myworkdayjobs.com", "myworkday.com", "taleo.net", "icims.com", "successfactors.", "oraclecloud.com",
               "brassring.com", "avature.net", "ultipro.com", "haystack", "jobvite.com/careers")
# Hosts that are an application form, or lead straight to one: an outbound
# link to these from an aggregator is the way to the employer's form.
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com", "breezy.hr",
             "recruitee.com", "teamtailor.com", "bamboohr.com", "personio.", "jobvite.com", "join.com",
             "jazzhr.com", "applytojob.com", "zohorecruit.", "freshteam.com", "keka.com", "darwinbox.",
             "hirist.", "instahyre.com", "cutshort.io", "wellfound.com", "relocate.me")
LOGINS_FILE = ROOT / "data" / "platform_logins.json"


def saved_logins() -> set[str]:
    """Hosts you signed in to with `python main.py --platform-login` (the automation browser keeps
    their session), so their "needs its own account" wall no longer applies."""
    try:
        return set(json.loads(LOGINS_FILE.read_text(encoding="utf-8")).get("hosts") or [])
    except (OSError, ValueError):
        return set()


def _needs_account(url: str) -> str | None:
    """The host, when the URL is a board or system that needs an account you have not saved."""
    url = (url or "").lower()
    have = saved_logins()
    for h in LOGIN_HOSTS + ACCOUNT_ATS:
        if h in url and not any(s in url for s in have):
            return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    return None


def _ats_form_url(url: str) -> str | None:
    for pattern, repl in ATS_FORM:
        if pattern.match(url or ""):
            return pattern.sub(repl, url)
    return None


def _outbound_apply(page) -> str | None:
    """On an aggregator's listing (Arbeitnow, JobThai, Duunitori, TokyoDev...), the link to the
    employer's application: an Apply-worded link leaving the site, else a link to a known
    application system."""
    try:
        links = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
            href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim(),
            vis: !!(a.offsetWidth || a.offsetHeight) }))""")
    except Exception:
        return None
    from urllib.parse import urlparse
    here = urlparse(page.url or "").netloc.replace("www.", "")
    apply_words = re.compile(r"apply|bewerb|postul|candidat|hae\b|haku|応募|エントリー|สมัคร|solicit|"
                             r"employer('s)? (web)?site|company('s)? (web)?site|zum arbeitgeber|zur stellenanzeige|werkgever", re.I)
    best = None
    for l in links:
        href = l.get("href") or ""
        if not href.startswith("http") or here and here in href:
            continue
        if apply_words.search(l.get("text") or "") and l.get("vis"):
            return href
        if best is None and any(h in href for h in ATS_HOSTS):
            best = href
    return best

# Ledger notes for company-site attempts start with this, so a posting is tried
# on its careers site once and then left alone.
TRIED = "company site: "

# Boards whose apply always needs an account there - not worth opening.
LOGIN_HOSTS = ("wellfound.com", "angel.co", "xing.com", "seek.com", "jobsdb.com", "jobstreet.com",
               "indeed.", "glassdoor.", "infojobs.net", "instahyre.com", "monster.", "foundit.in",
               "naukri.com/mnjuser", "linkedin.com/login", "simplyhired.")

# Aggregators: the posting page is never the application. Adzuna's "land"
# pages, Jooble, Arbeitnow, Remotive, ... show the ad with a search box and a
# job-alert box - filling those and looking for Submit is how 157 postings
# ended "filled 6 field(s) but found no Submit button". Their link out to the
# employer is followed instead.
AGGREGATOR_HOSTS = ("adzuna.", "jooble.", "arbeitnow.com", "remotive.", "remoteok.", "jobicy.", "workingnomads.",
                    "themuse.com", "landing.jobs", "landingjobs.", "careerjet.", "talent.com", "jobrapido.",
                    "neuvoo.", "jobs.google", "google.com/search", "duunitori.fi", "jobthai.com", "tokyodev.com",
                    "japan-dev.com", "daijob.com", "tecnoempleo.com", "infojobs.net", "wantedly.com")


def aggregator_host(url: str) -> bool:
    return any(h in _host(url) for h in AGGREGATOR_HOSTS)

# Job platforms: a form on one of these is the platform's own apply, not the
# employer's. Left alone while that platform's auto-apply is off
# (platform_switch.py), saved login or not.
# APPLY_ON_BOARD always apply on the board itself, so their postings are not
# even opened; the others often link out to the employer and are followed.
APPLY_ON_BOARD = ("naukri.com", "linkedin.com", "indeed.", "glassdoor.", "wellfound.com", "angel.co", "xing.com",
                  "seek.com", "jobsdb.com", "jobstreet.com", "instahyre.com", "hirist.", "cutshort.io", "relocate.me",
                  "monster.", "foundit.in", "simplyhired.", "stepstone.", "iimjobs.com", "shine.com", "timesjobs.com",
                  "apna.co", "internshala.com")
PLATFORM_HOSTS = APPLY_ON_BOARD + ("infojobs.net", "tecnoempleo.com", "duunitori.fi", "jobthai.com", "daijob.com",
                                   "wantedly.com")


def _host(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").lower()).split("/")[0]


def platform_host(url: str, hosts: tuple = PLATFORM_HOSTS) -> str | None:
    """The host, when `url` is on a job platform rather than the employer's own site."""
    host = _host(url)
    return host if any(h in host for h in hosts) else None


# Button texts, in the languages of the boards the search covers. Loose on
# purpose ("Apply for this job at Acme", "Jetzt bewerben", "応募する"), with the
# look-alikes that are not an application ruled out by NOT_ACTION.
APPLY_TEXT = re.compile(r"^\W*(apply|easy apply|quick apply|i'?m interested|start (your |an )?application|(jetzt )?bewerben|"
                        r"postular|postúlate|inscr[ií]b|solliciteer|hae\b|haku|candidat|応募|エントリー|สมัคร|"
                        # boards that send you on: XING "Visit employer website" / "Zum Arbeitgeber", SEEK "Apply on employer site"
                        r"visit (the )?(employer|company)('s)? ?(web)?site|go to (the )?(employer|company)('s)? ?(web)?site|"
                        r"zum arbeitgeber|zur (bewerbung|stellenanzeige)|externe bewerbung|auf (der )?(arbeitgeber|unternehmens)(web)?seite bewerben|"
                        r"naar (de )?werkgever|solicitar en (la )?web|postuler sur le site|hae työnantajan sivuilla|企業サイト)"
                        r".{0,45}$", re.I)
SUBMIT_TEXT = re.compile(r"^\W*(submit|send|apply|finish|complete (my |your )?application|bewerbung|absenden|"
                         r"enviar|envoyer|verzenden|verstuur|lähetä|送信|応募する|ส่ง)"
                         r".{0,30}$", re.I)
NOT_ACTION = re.compile(r"\b(filters?|alerts?|later|save (for|job)|similar|share|sign ?(in|up)|log ?in|register|"
                        r"with (linkedin|indeed|google|seek|xing)|go back|cancel|newsletter|"
                        # nav links and widgets that also say "apply" / "send": "Apply & Interview
                        # Resources" (Thermo Fisher), "How to apply", a chat box's Send, a search box
                        r"resources?|tips?|process|how to|faq|guide|interview|learn|events?|blog|chat|message|"
                        r"comment|subscribe|feedback|search|suche|zoeken|buscar|referr?al|refer a)\b", re.I)
# The page says the application went through on the board itself (Instahyre, Hirist,
# Cutshort, Wellfound ... one-click applies): the Apply button becomes "Applied".
APPLIED_TEXT = re.compile(r"^\W*(applied|application (sent|submitted)|you('ve| have) applied|already applied|"
                          r"bereits beworben|ya aplicaste|応募済み)\b", re.I)
NEXT_TEXT = re.compile(r"^\s*(next|next step|continue|save (and|&) continue|proceed|review|weiter|nächster schritt|siguiente|"
                       r"continuar|suivant|continuer|seuraava|jatka|volgende|次へ|次に進む|ถัดไป)\s*[›>→]?\s*$", re.I)
THANKS = re.compile(r"thank(s| you) for (applying|your (application|interest|submission))|application (has been |was )?"
                    r"(received|submitted|sent|complete|successful)|we('ve| have) received your application|"
                    r"successfully (applied|submitted|sent)|your application is on its way|"
                    r"your response has been recorded|we('ll| will) be in touch|you (have )?applied (to|for) this|"
                    r"application (is )?(under review|in progress)|"
                    r"vielen dank für (ihre|deine) bewerbung|bewerbung (wurde )?(erfolgreich )?(gesendet|eingereicht|übermittelt)|"
                    r"bedankt voor (je|uw) sollicitatie|sollicitatie (is )?(verzonden|ontvangen)|"
                    r"gracias por (tu|su) (candidatura|solicitud|postulación)|candidatura enviada|"
                    r"merci pour votre candidature|candidature (a été )?envoyée|kiitos hakemuksesta|hakemus(esi)? on (lähetetty|vastaanotettu)|"
                    r"応募(が)?完了|ご応募ありがとう|ส่งใบสมัคร(เรียบร้อย|สำเร็จ)", re.I)
# Cookie banners are declined, never accepted; pop-ups that are not the form are closed.
# In the languages of the boards the search covers: 15 of the "no Submit button"
# postings were an Adzuna page behind "ALLE ABLEHNEN" / "ALLES AFWIJZEN".
COOKIE_DECLINE = re.compile(r"^\W*((reject|decline|deny|refuse|disagree)( all| optional| non-essential| additional)?( cookies)?|"
                            r"(use |allow |accept )?(only )?(strictly )?(necessary|essential|required)( cookies)?( only)?|"
                            r"(alle |alles )?(ablehnen|verweigern|afwijzen|weigeren|rechazar( todo| todas)?|refuser( tout)?|"
                            r"tout refuser|hylkää( kaikki)?|kieltäydy|rifiuta( tutto)?|すべて拒否|拒否|ปฏิเสธ(ทั้งหมด)?)|"
                            r"nur (notwendige|erforderliche|essenzielle)( cookies)?( zulassen| akzeptieren)?|"
                            r"alleen (noodzakelijke|essentiële|functionele)( cookies)?( toestaan| accepteren)?|"
                            r"s[oó]lo (las )?(necesarias|esenciales|imprescindibles)( cookies)?|"
                            r"(uniquement|seulement) (les )?(cookies )?(nécessaires|essentiels)|vain välttämättömät( evästeet)?)\W*$", re.I)
POPUP_CLOSE = re.compile(r"^\W*(no,? thanks?( you)?|not now|maybe later|close|dismiss|skip( for now)?|×|✕|✖|x)\W*$", re.I)
# Boxes that are not the application: job alerts, newsletters, site search.
NOT_THE_FORM = re.compile(r"job alert|create (an |email )?alert|receive (an )?alert|jobs by email|similar jobs|newsletter|"
                          r"subscribe|talent (community|network|pool)|search jobs|keyword|\brole=search\b", re.I)
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
    ("state", r"^\s*state\b|state\s*/\s*(province|region|ut)|\bprovince\b"),
    ("pincode", r"pin\s*code|postal\s*code|zip\s*code|^\s*zip\b"),
    ("city", r"^\s*city|current\s*city|town"),
    ("location", r"location|where\s+(are\s+you|do\s+you)\s+(based|live)|address"),
    ("country", r"^\s*country"),
    ("hear", r"how\s+did\s+you\s+(hear|find|learn)|source|referr?al\s*source"),
    ("eeo", r"gender|race|ethnic|veteran|disabilit|sexual\s*orientation|pronoun|hispanic|latino"),
    ("consent", r"privacy|consent|i\s+agree|terms|acknowledg|data\s*(protection|processing)|gdpr"),
]
EEO = re.compile(dict(FIELD_RULES)["eeo"], re.I)
CONSENT_Q = re.compile(r"i\s+agree|consent|acknowledg|certify|terms (and|&) conditions|privacy (policy|notice)", re.I)
AGREE = re.compile(r"^\W*(yes|i agree|agree|i accept|accept|i confirm|confirm|i understand|i acknowledge|acknowledged?)\b", re.I)
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
      // an ancestor's label names this field only when the ancestor wraps this one field
      if (p.querySelectorAll('input:not([type=hidden]), select, textarea').length > 1) break;
      const c = p.querySelector('label, legend, .label, [class*=label], [class*=question]'); if (c && !c.contains(e)) t = txt(c); } }
    if (!t) {
      // a combobox whose label is not linked to it (Greenhouse's React selects read as "Select..."):
      // the nearest block of text above the field, walking up through its ancestors
      let node = e;
      for (let i = 0; i < 5 && node && !t; i++, node = node.parentElement) {
        for (let sib = node.previousElementSibling; sib && !t; sib = sib.previousElementSibling) {
          if (sib.querySelector('input, select, textarea, button')) break;
          const s0 = txt(sib); if (s0 && s0.length <= 220) t = s0;
        }
      }
    }
    return t.slice(0, 300);
  };
  // the box a field sits in (form / dialog / section): job-alert and search boxes are not the application
  const ctxOf = e => {
    // no form / dialog around it: the field's own small wrapper (a "create alert" box is often a bare div)
    const c = e.closest('form, [role=dialog], dialog, [role=search], aside, section') ||
      (e.parentElement && e.parentElement.parentElement !== document.body ? e.parentElement.parentElement : e.parentElement);
    if (!c) return { ctx: '', ctxFields: 99 };
    return { ctx: [c.tagName, c.id || '', String(c.getAttribute('class') || ''), c.getAttribute('role') || '',
                   c.getAttribute('aria-label') || '', txt(c).slice(0, 200)].join(' '),
             ctxFields: c.querySelector('input[type=file]') ? 99 :
               c.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select').length };
  };
  const out = []; let n = 0, g = 0;
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
      password: type === 'password',
      combo: e.tagName === 'INPUT' && !['tel', 'email', 'url', 'number', 'date'].includes(type) &&
        (e.getAttribute('role') === 'combobox' || e.getAttribute('aria-autocomplete') === 'list' ||
         e.getAttribute('aria-haspopup') === 'listbox' || !!e.closest('[class*="select__control"], [class*="react-select"], [class*="Select-control"]')),
      ...ctxOf(e) });
  });
  // Google Forms and other ARIA widgets: div radios / checkboxes / dropdowns
  document.querySelectorAll('[role=radio], [role=checkbox], [role=listbox]').forEach(e => {
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName) || e.querySelector('input, select')) return;
    if (!vis(e) || e.getAttribute('aria-disabled') === 'true') return;
    const role = e.getAttribute('role');
    const item = e.closest('[role=listitem], fieldset, [role=radiogroup], [role=group]');
    const grp = e.closest('[role=radiogroup], [role=group], [role=listitem], fieldset');
    let q = '';
    const head = item && item.querySelector('[role=heading], legend');
    if (head) q = txt(head);
    if (!q && grp && grp.getAttribute('aria-labelledby')) q = grp.getAttribute('aria-labelledby').split(' ').map(i => txt(document.getElementById(i))).join(' ');
    if (!q && grp) q = grp.getAttribute('aria-label') || '';
    if (!q) q = labelOf(e);
    let gid = '';
    if (grp && role !== 'listbox') { if (!grp.getAttribute('data-ca-g')) grp.setAttribute('data-ca-g', 'g' + (g++)); gid = grp.getAttribute('data-ca-g'); }
    const idx = String(n++); e.setAttribute('data-ca', idx);
    const picked = role === 'listbox' ? e.querySelector('[role=option][aria-selected=true]') : null;
    out.push({ idx, tag: 'aria', type: role === 'listbox' ? 'aria-select' : role, name: '', id: e.id || '',
      placeholder: '', autocomplete: '', label: q.slice(0, 300), legend: q.slice(0, 300), group: gid,
      optionLabel: (e.getAttribute('aria-label') || e.getAttribute('data-value') || e.getAttribute('data-answer-value') || txt(e)).trim(),
      value: picked ? (picked.getAttribute('data-value') || '') : '', checked: e.getAttribute('aria-checked') === 'true',
      required: /\*\s*$/.test(q) || !!(item && item.querySelector('[aria-label*="required" i]')) || (grp && grp.getAttribute('aria-required') === 'true'),
      options: role === 'listbox' ? Array.from(e.querySelectorAll('[role=option]')).map(o => (o.getAttribute('data-value') || txt(o)).trim()).filter(Boolean) : [],
      selectedText: '', password: false, ...ctxOf(e) });
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
    # "gurgaon ,haryana , india" (the dashboard's current location) -> Gurgaon / Haryana / India
    place = [p.strip().title() for p in str(app.get("location") or (config.get("fact_overrides") or {}).get("current_location")
                                             or profile.get("location") or "").split(",") if p.strip()]
    location = ", ".join(place)
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
        "city": app.get("city") or (place[0] if place else ""),
        "state": app.get("state") or (place[1] if len(place) >= 3 else ""),
        "country": app.get("country") or (place[-1] if len(place) >= 2 else ""),
        "pincode": str(app.get("pincode") or app.get("zip") or ""),
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


def login_wall(page, text: bool = True) -> str | None:
    """A login URL or a visible password box; with `text`, also a "sign in to apply" line -
    checked only when no form was found, since Workable and friends print "Already have an
    account?" next to a form that needs none."""
    if LOGIN_URL.search(page.url or "") and not re.search(r"/apply", page.url or "", re.I):
        return "the site sends you to a login page"
    for frame in _frames(page):
        try:
            if _visible(frame.locator("input[type=password]")):
                return "the site asks for a login / account"
        except Exception:
            continue
    if not text:
        return None
    body = _body(page)
    m = LOGIN_WALL.search(body)
    if m:
        return f"the site says '{m.group(0)}'"
    return None


CAPTCHA_JS = r"""
(() => {
  // A CAPTCHA a person would have to solve: a checkbox widget or an open challenge. NOT the
  // invisible reCAPTCHA badge in the corner (size=invisible, ~70px) - every Greenhouse board
  // and many career sites carry that badge, and it was read as "CAPTCHA - apply by hand".
  const shown = e => { const r = e.getBoundingClientRect(); if (r.width < 120 || r.height < 40) return false;
    for (let p = e; p; p = p.parentElement) { const s = getComputedStyle(p);
      if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity || '1') < 0.2) return false; }
    return true; };
  for (const f of document.querySelectorAll('iframe')) {
    const src = (f.src || '') + ' ' + (f.title || '');
    if (/recaptcha\/(api2|enterprise)\/anchor/.test(src)) { if (!/size=invisible/.test(src) && shown(f)) return 'recaptcha checkbox'; }
    else if (/recaptcha\/(api2|enterprise)\/bframe/.test(src)) { if (shown(f)) return 'recaptcha challenge'; }
    else if (/hcaptcha\.com/.test(src)) { if (shown(f)) return 'hcaptcha'; }
    else if (/challenges\.cloudflare\.com/.test(src)) { if (shown(f)) return 'cloudflare turnstile'; }
    else if (/captcha/i.test(f.title || '')) { if (shown(f)) return 'captcha'; }
  }
  const img = document.querySelector('img[src*="captcha" i], img[alt*="captcha" i], input[name*="captcha" i]:not([type=hidden])');
  return img && shown(img.tagName === 'INPUT' ? img : img) ? 'image captcha' : '';
})()
"""


def captcha(page) -> str:
    """The CAPTCHA that blocks the form ("recaptcha checkbox", "hcaptcha", ...) - a checkbox /
    image challenge, not the invisible badge. Empty when there is none."""
    for frame in _frames(page)[:4]:
        try:
            kind = frame.evaluate(CAPTCHA_JS)
            if kind:
                return str(kind)
        except Exception:
            continue
    return ""


OVERLAY_JS = r"""
(() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(e).visibility !== 'hidden'; };
  const txt = e => (e.innerText || e.value || '').replace(/\s+/g, ' ').trim();
  const out = []; let k = 0;
  document.querySelectorAll('button, a, [role=button], input[type=button]').forEach(b => {
    if (!vis(b)) return;
    const box = b.closest('[role=dialog], dialog, [aria-modal=true], [class*=modal i], [class*=popup i], [class*=overlay i], ' +
      '[id*=cookie i], [class*=cookie i], [id*=consent i], [class*=consent i], [id*=onetrust i], [class*=banner i]');
    if (!box) return;
    const formy = !!box.querySelector('input[type=file]') ||
      box.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea, select').length > 2;
    b.setAttribute('data-ca-x', String(k));
    out.push({ k: String(k++), t: txt(b).slice(0, 60), aria: (b.getAttribute('aria-label') || '').slice(0, 60), formy,
      cookie: /cookie|consent|gdpr|onetrust|privacy/i.test([box.id, box.getAttribute('class') || '', txt(box).slice(0, 400)].join(' ')) });
  });
  return out;
})()
"""


def dismiss_overlays(page) -> int:
    """Decline a cookie banner and close pop-ups that are not the application form.
    Returns how many were clicked."""
    clicked = 0
    for frame in _frames(page)[:4]:
        for _round in range(3):
            try:
                found = frame.evaluate(OVERLAY_JS)
            except Exception:
                break
            pick = next((b for b in found if b["cookie"] and COOKIE_DECLINE.match(b["t"] or b["aria"])), None)
            if pick is None:
                pick = next((b for b in found if not b["formy"] and not b["cookie"]
                             and (POPUP_CLOSE.match(b["t"] or "") or re.fullmatch(r"\s*(close|dismiss)( dialog| modal| popup)?\s*",
                                                                                   b["aria"] or "", re.I))), None)
            if pick is None:
                break
            try:
                human.click(frame.page, frame.locator(f'[data-ca-x="{pick["k"]}"]').first, timeout=3000)
                clicked += 1
                frame.wait_for_timeout(700)
            except Exception:
                break
    return clicked


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
                        human.click(frame.page, el, timeout=6000)
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
        fields = [f for f in fields if not _not_the_form(f)]
        useful = [f for f in fields if f["type"] not in ("checkbox",) or f["required"]]
        if len(useful) > len(best_fields):
            best, best_fields = frame, fields
    return best, best_fields


SEARCH_BOX = re.compile(r"search|keyword|\bquery\b|\bsuche|zoek|buscar|recherche|\bhaku|検索|ค้นหา|"
                        r"^(q|w|l|what|where|kw|loc|was|wo|wat|waar)$|^(job|vacature|stelle|puesto|emploi), ", re.I)


def _not_the_form(field: dict) -> bool:
    """A job-alert, newsletter or search box (a small one - a whole-page <form> is not judged by its text)."""
    if any(SEARCH_BOX.search(part or "") for part in (field["name"], field["id"], field["placeholder"], field.get("autocomplete"))):
        return True
    return field.get("ctxFields", 99) <= 3 and bool(NOT_THE_FORM.search(field.get("ctx") or ""))


# A "Get in touch" / "Request a quote" box on a company's home page: name, e-mail, phone,
# "tell us about your project", Send Message. Not an application, however many fields.
CONTACT_FORM = re.compile(r"get in touch|contact (us|form)|send (us )?(a )?message|your project|project ?type|"
                          r"request a (quote|demo|call)|book a (call|demo)|enquir|inquir|how can we help|"
                          r"subject|newsletter|subscribe|kontakt(formular)?|neem contact|contáct|contactez", re.I)


def looks_like_application(fields: list[dict], buttons: str = "") -> bool:
    """Is this set of fields an application form, not a search / alert / contact box?

    A resume upload settles it; else an e-mail box with a name or phone box;
    else a textarea or select with a question. Two lone text boxes - a search
    box and an alert e-mail - are not, and neither is a contact form (its
    labels / box / button say so), whatever it asks for.
    """
    fillable = [f for f in fields if f["type"] not in ("checkbox", "radio")]
    if any(f["type"] == "file" for f in fillable):
        return True
    around = " ".join(" ".join([f["label"], f["name"], f["placeholder"], f["legend"], (f.get("ctx") or "")[:200]])
                      for f in fillable)
    if CONTACT_FORM.search(around + " " + buttons) and not re.search(r"resume|\bcv\b|curriculum|cover letter|applicant|candidat|position|vacancy|job", around, re.I):
        return False
    meanings = {_meaning(f) for f in fillable}
    if "email" in meanings and (meanings & {"first_name", "last_name", "full_name", "phone", "linkedin", "resume"}):
        return True
    if any(f["tag"] in ("textarea", "select") or f["type"] == "aria-select" for f in fillable) and len(fillable) >= 3:
        return True
    return len(fillable) >= 5


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
    placeholder = field["placeholder"] if not PLACEHOLDER.match(field["placeholder"] or "") else ""   # "Select..." is no question
    return (field["legend"] or field["label"] or placeholder or field["name"]).strip(" *")


def _cover(who: dict, job: dict) -> str:
    if who.get("cover_letter"):
        return who["cover_letter"]
    title, company = job.get("title") or "this role", job.get("company") or "your team"
    return (f"Dear Hiring Team,\n\nI would like to apply for {title} at {company}. I am a "
            f"{who.get('current_title') or 'software engineer'}"
            f"{' at ' + who['current_company'] if who.get('current_company') else ''}; my resume is attached "
            f"and my profile is at {who.get('linkedin') or who.get('github') or ''}.\n\nKind regards,\n{who.get('name')}")


VERIFY_Q = re.compile(r"verification code|enter the \d+.?(character|digit) code|code (was |we )?(sent|e-?mailed) to|one.?time (code|password)|\botp\b", re.I)
MOTIVATION_Q = re.compile(r"why (do you want|are you interested|us|this (role|job|company))|interest(s|ed)? (you )?(in|about)|motivat|"
                          r"about (you|yourself)|tell us|introduce yourself|(cover|application) (letter|note|message)|"
                          r"^\W*(message|note|additional (information|comments?))\W*$", re.I)


def _motivation(who: dict, job: dict) -> str:
    title, company = job.get("title") or "this role", job.get("company") or "your team"
    me = who.get("current_title") or "software engineer"
    at = f" at {who['current_company']}" if who.get("current_company") else ""
    return (f"I'm interested in the {title} role at {company} because it is close to the work I do today as a {me}{at}: "
            f"building and running production backend systems and the data pipelines behind them. I'd like to bring that "
            f"experience to your product and grow with the team. My resume has the details, and I'm available to talk "
            f"whenever convenient.")


MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _iso_date(text: str) -> str | None:
    """'23 / 09 / 2003' or '2003-09-23' -> '2003-09-23' (what <input type=date> takes)."""
    text = str(text or "")
    named = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", text)
    if named:
        month = MONTHS.get(named.group(2)[:3].lower())
        text = f"{named.group(1)}/{month}/{named.group(3)}" if month else text
    m = re.search(r"(\d{1,4})\s*[/\-. ]\s*(\d{1,2})\s*[/\-. ]\s*(\d{1,4})", text)
    if not m:
        return None
    a, b, c = m.groups()
    y, mo, d = (a, b, c) if len(a) == 4 else (c, b, a)     # otherwise DD/MM/YYYY, as Indian forms write it
    if len(y) == 2:
        y = "20" + y if int(y) < 50 else "19" + y
    try:
        from datetime import date as _date
        return _date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def _shaped(field: dict, value) -> str | None:
    """The value as the input takes it: an ISO date for a date box, a bare number for a number box."""
    text = str(value)
    if field["type"] == "date":
        return _iso_date(text)
    if field["type"] == "number":
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return m.group(0) if m else None
    return text


def _stable(frame, field: dict):
    """The field found by its id, name or label - for when its data-ca tag was lost to a re-render."""
    if field["id"]:
        return frame.locator(f'[id={json.dumps(field["id"])}]').first
    if field["name"]:
        return frame.locator(f'{field["tag"]}[name={json.dumps(field["name"])}]').first
    return frame.get_by_label(field["label"].strip(" *")[:80]).first


COMBO_OPTIONS = ("[role=option]:visible, [role=listbox] li:visible, [class*='__option']:visible, [class*='-option']:visible, "
                 ".pac-item:visible, [class*='suggestion' i]:visible, [class*='autocomplete' i] li:visible, [class*='menu' i] [class*='item' i]:visible")
WHO_FIELDS = ("first_name", "last_name", "email", "phone", "linkedin", "github", "website", "current_company", "current_title",
              "city", "state", "pincode", "location", "country")


def _combo_options(frame) -> list[str]:
    try:
        return [t.strip() for t in frame.locator(COMBO_OPTIONS).all_inner_texts()[:60] if t.strip()]
    except Exception:
        return []


def _click_option(frame, pg, text: str) -> bool:
    try:
        opt = frame.locator(COMBO_OPTIONS).filter(has_text=re.compile(r"^\s*" + re.escape(text) + r"\s*$", re.I)).first
        if not opt.count():
            opt = frame.locator(COMBO_OPTIONS).filter(has_text=text).first
        human.click(pg, opt, timeout=4000)
        return True
    except Exception:
        return False


def _fill_combo(frame, pg, f: dict, q: str, meaning, who: dict, ask, record) -> tuple[bool, str | None]:
    """A combobox: open it, read its options and choose the answer; an autocomplete (a
    location box): type your value and take the matching suggestion. Returns (filled, the
    question when it could not be answered)."""
    from . import answers as answers_mod
    if meaning in ("phone", "email", "first_name", "last_name", "full_name", "linkedin", "github", "website", "pincode"):
        # plain identity boxes are never a dropdown, whatever their wrapper's class says: the
        # phone number once went into the country picker ("British Indian Ocean Territory")
        human.type_into(pg, frame.locator(f'[data-ca="{f["idx"]}"]'), str(who.get(meaning) or who.get("github") or ""), timeout=5000)
        record(q, who.get(meaning) or "", meaning)
        return True, None
    box = frame.locator(f'[data-ca="{f["idx"]}"]')
    human.click(pg, box, timeout=4000)
    frame.wait_for_timeout(900)
    opts = _combo_options(frame)
    value = who.get(meaning) or None if meaning in WHO_FIELDS else None
    if meaning == "website" and not value:
        value = who.get("github") or who.get("linkedin") or None
    listy = opts and not re.search(r"no (options|results)|start typing|type to search|search\.\.\.", " ".join(opts), re.I)
    if listy and value is None:
        # a question with a fixed list ("right to work?": Yes / No)
        answer, why = ask(q, opts)
        choice = answers_mod.choose_option(answer, opts) if answer is not None else None
        if choice is None:
            pg.keyboard.press("Escape")
            return False, q
        if _click_option(frame, pg, choice):
            record(q, choice, why)
            return True, None
        pg.keyboard.press("Escape")
        return False, q
    why = meaning or "answers"
    if value is None:
        answer, why = ask(q, [])
        if answer is None:
            pg.keyboard.press("Escape")
            return False, q
        value = str(answer)
    typed = str(value)
    if meaning in ("location", "city") and who.get("city"):
        typed = who["city"]                      # "Gurugram" finds the suggestion; the full address does not
    pg.keyboard.type(typed, delay=random.uniform(45, 110))
    frame.wait_for_timeout(1600)
    opts = _combo_options(frame)
    if opts:
        pick = None
        if meaning in ("location", "city"):
            # the suggestion that matches your whole location - state counts most: "Gurgaon,
            # Bihar, India" was chosen over the Haryana one, and "Gurgaon" / "Gurugram" are one city
            city = {(who.get("city") or typed).lower()}
            if city & {"gurugram", "gurgaon"}:
                city |= {"gurugram", "gurgaon"}
            state, country = (who.get("state") or "").lower(), (who.get("country") or "").lower()

            def score(o: str) -> int:
                words = set(re.findall(r"[a-z]+", o.lower()))
                return 3 * bool(state and state in words) + 2 * bool(city & words) + bool(country and country in words)
            scored = sorted(((score(o), -i, o) for i, o in enumerate(opts)), reverse=True)
            if scored and scored[0][0] > 0:
                pick = scored[0][2]
        if pick is None:
            # a whole-word match: "India" is not "British Indian Ocean Territory"
            head = typed.split(",")[0].strip().lower()
            wordy = re.compile(r"(?<![a-z])" + re.escape(head) + r"(?![a-z])") if head else None
            pick = next((o for o in opts if wordy and wordy.search(o.lower())), None)
            if pick is None and wordy:
                pick = next((o for o in opts if o.lower().startswith(head)), None)
        if pick is None and listy:
            pick = answers_mod.choose_option(typed, opts) or None
        if pick is None:
            pick = opts[0]
        if not _click_option(frame, pg, pick):
            pg.keyboard.press("Tab")   # never Enter: that submits a half-filled form
        record(q, pick, why)
    else:
        pg.keyboard.press("Tab")   # never Enter: that submits a half-filled form
        record(q, typed, why)
    frame.wait_for_timeout(400)
    return True, None


def fill_form(frame, fields: list[dict], who: dict, facts: dict, job: dict, capture: dict) -> tuple[int, list[str]]:
    """Fill what can be filled from facts. Returns (filled, unanswered required questions)."""
    from . import answers as answers_mod

    filled, blocked = 0, []
    groups: dict[str, list[dict]] = {}
    for f in fields:
        if f["type"] in ("radio", "checkbox") and f["group"]:
            groups.setdefault(f["group"], []).append(f)
    pg = frame.page

    def loc(f):
        return frame.locator(f'[data-ca="{f["idx"]}"]')

    def tick(f):
        # a div radio / checkbox (Google Forms) takes a click; a real one too - by hand,
        # then the DOM check only when the click did not take (a hidden native box)
        human.click(pg, loc(f), timeout=4000)
        if f["tag"] != "aria":
            try:
                if not loc(f).is_checked(timeout=1500):
                    loc(f).check(timeout=4000, force=True)
            except Exception:
                loc(f).check(timeout=4000, force=True)
        human.pause(pg, 250, 800)

    def ask(q, options, long_text=False):
        return answers_mod.resolve(q, options, facts, job=job, long_text=long_text)

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
                        tick(f)
                        filled += 1
                        record(q, "checked", "consent")
                    elif required:
                        # "Joining WhatsApp is Mandatory": your rules / saved answers decide
                        answer, why = ask(q, ["Yes", "No"])
                        if answer is not None and answers_mod.choose_option(answer, ["Yes", "No"]) == "Yes":
                            tick(f)
                            filled += 1
                            record(q, "checked", why)
                        else:
                            blocked.append(q)
                            capture.setdefault("question", q)
                            capture.setdefault("why", why)
                    continue
                options = [m["optionLabel"] or m["label"] for m in members]
                if required and (meaning == "consent" or CONSENT_Q.search(q or "")):
                    # "By submitting this application, I agree ..." offered as a group
                    pick = next((m for m in members if AGREE.match(m["optionLabel"] or m["label"])), None)
                    if pick:
                        tick(pick)
                        filled += 1
                        record(q, pick["optionLabel"] or pick["label"], "consent")
                        continue
                if meaning == "eeo" or EEO.search(q or ""):
                    pick = next((m for m in members if DECLINE.search(m["optionLabel"] or m["label"])), None)
                    if pick is None and required:
                        # no "prefer not to say": only an answer you saved (gender ...) is used
                        answer, _why = ask(q, options)
                        choice = answers_mod.choose_option(answer, options) if answer is not None else None
                        pick = next((m for m in members if (m["optionLabel"] or m["label"]) == choice), None)
                    if pick:
                        tick(pick)
                        filled += 1
                    elif required:
                        blocked.append(q)
                    continue
                answer, why = ask(q, options)
                choice = answers_mod.choose_option(answer, options) if answer is not None else None
                if choice is None:
                    if required:
                        blocked.append(q)
                        capture.setdefault("question", q)
                        capture.setdefault("options", options)
                        capture.setdefault("why", why)
                    continue
                target = next(m for m in members if (m["optionLabel"] or m["label"]) == choice)
                tick(target)
                filled += 1
                record(q, choice, why)
                continue

            # ---- ARIA dropdowns (Google Forms): open the list, click the option
            if f["type"] == "aria-select":
                if f["value"]:
                    continue
                options = [o for o in f["options"] if not PLACEHOLDER.match(o)]
                answer, why = ask(q, options)
                choice = answers_mod.choose_option(answer, options) if answer is not None else None
                if choice is None:
                    if f["required"]:
                        blocked.append(q)
                        capture.setdefault("question", q)
                        capture.setdefault("options", options)
                    continue
                human.click(pg, loc(f), timeout=4000)
                frame.wait_for_timeout(700)
                human.click(pg, frame.locator(f'[role=option][data-value={json.dumps(choice)}]:visible').first, timeout=4000)
                frame.wait_for_timeout(500)
                filled += 1
                human.pause(pg)
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
                    human.hover(pg, loc(f))
                    loc(f).set_input_files(who["resume"], timeout=8000)
                    filled += 1
                    human.pause(pg, 600, 1500)
                elif f["required"] and meaning != "resume":
                    blocked.append(q or "file upload")
                continue

            # ---- comboboxes and autocompletes (Greenhouse's React selects, Google Places boxes):
            # typing into the box does nothing until an option is chosen
            if f.get("combo") and f["tag"] == "input":
                ok, block_q = _fill_combo(frame, pg, f, q, meaning, who, ask, record)
                if ok:
                    filled += 1
                    human.pause(pg, 250, 800)
                elif f["required"]:
                    blocked.append(block_q or q or "a required field")
                    capture.setdefault("question", q)
                continue

            # ---- plain values from your details
            value = None
            if meaning in ("first_name", "last_name", "email", "phone", "linkedin", "github", "website",
                           "current_company", "current_title", "city", "state", "pincode", "location", "country"):
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
                if pick is None and f["required"]:
                    answer, _why = ask(q, [o for o in f["options"] if not PLACEHOLDER.match(o)])
                    pick = answers_mod.choose_option(answer, f["options"]) if answer is not None else None
                if pick:
                    human.hover(pg, loc(f))
                    loc(f).select_option(label=pick, timeout=4000)
                    filled += 1
                    human.pause(pg)
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
                    answer, why = ask(q, options)
                    choice = answers_mod.choose_option(answer, options) if answer is not None else None
                if choice is None:
                    if f["required"]:
                        blocked.append(q)
                        capture.setdefault("question", q)
                        capture.setdefault("options", options)
                    continue
                human.hover(pg, loc(f))
                loc(f).select_option(label=choice, timeout=4000)
                filled += 1
                record(q, choice, meaning or "answers")
                human.pause(pg)
                continue

            if value is None:
                if VERIFY_Q.search(q or ""):
                    # "enter the 8-character code we e-mailed you": read it from your inbox
                    from . import mailcode
                    code = mailcode.wait_for_code()
                    if code:
                        answer, why = code, "verification code from your inbox"
                    else:
                        blocked.append("the e-mail verification code" + ("" if mailcode.configured() else
                                                                          " (set up Gmail under Settings so the PC can read it)"))
                        capture.setdefault("question", q)
                        continue
                else:
                    answer, why = ask(q, [], long_text=f["tag"] == "textarea") if q else (None, "")
                if answer is None and f["tag"] == "textarea" and MOTIVATION_Q.search(q or ""):
                    # "what interests you about working here?": never sent blank - a plain paragraph
                    # from your details when the written answer is not available (model budget spent)
                    answer, why = _motivation(who, job), "template (no written answer available)"
                if answer is None:
                    if f["required"]:
                        blocked.append(q or f["name"] or "a required field")
                        capture.setdefault("question", q)
                        capture.setdefault("why", why)
                    continue
                value = answer
                record(q, answer, why)
            value = _shaped(f, value)
            if value is None:
                if f["required"]:
                    blocked.append(q or "a required field")
                continue
            try:
                if f["type"] in ("date", "number", "time", "month", "week", "color", "range"):
                    human.click(pg, loc(f), timeout=5000)
                    loc(f).fill(value, timeout=5000)          # typed digits do not land in a date box
                else:
                    human.type_into(pg, loc(f), value, timeout=5000)
            except Exception:
                # the page re-rendered while the model was writing: find the box again by what does not change
                _stable(frame, f).fill(value, timeout=5000)
            filled += 1
            human.pause(pg, 250, 900)
            # Autocomplete boxes (city pickers) want a pick from their list.
            if meaning in ("city", "location"):
                frame.wait_for_timeout(900)
                try:
                    option = frame.locator("[role=option]").first
                    if option.is_visible(timeout=700):
                        human.click(pg, option, timeout=3000)
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001 - one odd widget should not sink the form
            log.debug("could not fill %r: %s", q, exc)
            if f.get("required"):
                blocked.append(q or "a required field")
    return filled, blocked


# ------------------------------------------------------------------ the attempt

def _shot(page, job: dict, suffix: str = "", full: bool = False) -> str:
    """A screenshot of the page's state. `full` (the whole page, for "no Submit button" and
    "no confirmation") so the reason is in the picture, not below the fold."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^a-z0-9]+", "-", (job.get("company", "") + "-" + job.get("title", "")).lower())[:60].strip("-") or "posting"
    path = SHOTS / f"{time.strftime('%Y%m%d-%H%M')}-{key}{suffix}.png"
    try:
        page.screenshot(path=str(path), full_page=full)
    except Exception:
        try:
            page.screenshot(path=str(path), full_page=False)
        except Exception:
            return ""
    return str(path)


APPLY_JS = r"""
(() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(e).visibility !== 'hidden'; };
  const txt = e => (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
  const out = []; let k = 0;
  document.querySelectorAll('button, a, [role=button], input[type=submit], input[type=button]').forEach(b => {
    if (!vis(b)) return;
    const t = txt(b); if (!t || t.length > 70) return;
    b.setAttribute('data-ca-a', String(k));
    out.push({ k: String(k++), t, href: b.href || b.getAttribute('href') || '',
      inNav: !!b.closest('nav, header, footer, [role=navigation], [role=menu], [class*=navbar i], [class*=footer i], [class*=site-header i], [class*=menu i]'),
      inMain: !!b.closest('main, article, [role=main], form, [class*=job i], [class*=posting i], [class*=vacancy i], [class*=position i], [class*=apply i], [id*=job i], [id*=apply i]'),
      isButton: b.tagName !== 'A', y: b.getBoundingClientRect().top + window.scrollY });
  });
  return out;
})()
"""


def _click_apply(page) -> bool:
    """Press the posting's own Apply control - the most likely one, not the first.

    The first text match used to win, which on Thermo Fisher was the nav link
    "Apply & Interview Resources". Now: nav / header / footer links are out,
    buttons and links whose href says apply (or leads to an application
    system) rank first, the job's own section before the rest, then the
    higher one on the page.
    """
    for frame in _frames(page)[:4]:
        try:
            found = frame.evaluate(APPLY_JS)
        except Exception:
            continue
        ranked = []
        for b in found:
            text = b["t"]
            if not APPLY_TEXT.match(text) or NOT_ACTION.search(text):
                continue
            href = (b.get("href") or "").lower()
            score = 0
            score += 4 if ("apply" in href or "bewerb" in href or "candidat" in href or any(h in href for h in ATS_HOSTS)) else 0
            score += 3 if b["inMain"] else 0
            score += 2 if b["isButton"] else 0
            score -= 10 if b["inNav"] else 0
            score -= 3 if href.startswith("mailto:") else 0
            ranked.append((score, b["y"], b["k"]))
        for score, _y, k in sorted(ranked, key=lambda r: (-r[0], r[1])):
            if score < 0:
                break
            try:
                human.click(frame.page, frame.locator(f'[data-ca-a="{k}"]').first, timeout=6000)
                return True
            except Exception:
                continue
    return False


SUBMIT_JS = r"""
(() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(e).visibility !== 'hidden'; };
  const txt = e => (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
  const marked = Array.from(document.querySelectorAll('[data-ca]'));
  const forms = new Map();
  marked.forEach(e => { const f = e.closest('form'); if (f) forms.set(f, (forms.get(f) || 0) + 1); });
  let form = null, best = 0; forms.forEach((n, f) => { if (n > best) { best = n; form = f; } });
  const scope = form || (marked.length ? (marked[0].closest('[role=dialog], dialog, section, main, article') || document) : document);
  const out = []; let k = 0;
  scope.querySelectorAll('button, input[type=submit], input[type=button], [role=button], a').forEach(b => {
    if (!vis(b)) return;
    b.setAttribute('data-ca-s', String(k));
    out.push({ k: String(k++), t: txt(b).slice(0, 60), type: (b.getAttribute('type') || '').toLowerCase(), inForm: !!form,
      disabled: !!(b.disabled || b.getAttribute('aria-disabled') === 'true') });
  });
  return out;
})()
"""


def _press_submit(frame, page) -> str | None:
    """Press the filled form's own Submit (or Next) button. Returns "submit" / "next" / None.

    The button is looked for inside the <form> that holds the fields just
    filled - a page-wide text match picked the chat widget's "Send" on
    Designoweb and the job-alert box's "Subscribe" elsewhere, and the real
    "Submit Application" was never pressed.
    """
    try:
        found = [b for b in frame.evaluate(SUBMIT_JS) if not b["disabled"]]
    except Exception:
        found = []
    scoped = [b for b in found if b["inForm"]]
    order = [
        ("submit", [b for b in scoped if b["type"] == "submit" and (not b["t"] or SUBMIT_TEXT.match(b["t"]) or not NOT_ACTION.search(b["t"]))]),
        ("submit", [b for b in scoped if SUBMIT_TEXT.match(b["t"]) and not NOT_ACTION.search(b["t"])]),
        ("next", [b for b in scoped if NEXT_TEXT.match(b["t"])]),
        ("submit", [b for b in found if SUBMIT_TEXT.match(b["t"]) and not NOT_ACTION.search(b["t"])]),
        ("next", [b for b in found if NEXT_TEXT.match(b["t"])]),
        ("submit", [b for b in scoped if b["type"] == "submit"]),
    ]
    for kind, cands in order:
        for b in cands:
            try:
                human.click(frame.page, frame.locator(f'[data-ca-s="{b["k"]}"]').first, timeout=5000)
                return kind
            except Exception:
                continue
    # nothing marked (Simplify filled everything): the page-wide text match, as before
    if _click_text(frame, SUBMIT_TEXT) or _click_text(page, SUBMIT_TEXT):
        return "submit"
    if _click_text(frame, NEXT_TEXT) or _click_text(page, NEXT_TEXT):
        return "next"
    try:
        human.click(frame.page, frame.locator("button[type=submit], input[type=submit]").first, timeout=5000)
        return "submit"
    except Exception:
        return None


FEEDBACK = ("[role=alert]:visible, [role=status]:visible, [aria-live]:visible, [class*=toast i]:visible, [class*=snackbar i]:visible, "
            "[class*=notification i]:visible, [class*=success i]:visible, [class*=alert i]:visible, [class*=message i]:visible, "
            "[class*=error i]:visible, [class*=fail i]:visible, [class*=status i]:visible")
# The page's own words for a submission that did not go through.
PAGE_ERROR = re.compile(r"failed to submit|please try again|something went wrong|an error (has )?occurred|could not (be )?submit|"
                        r"submission failed|unable to (submit|process)|try again later", re.I)


def _form_buttons(frame) -> str:
    """The texts of the buttons in the form the fields sit in ("Send Message" tells a contact form)."""
    try:
        return " ".join(b["t"] for b in frame.evaluate(SUBMIT_JS) if b.get("inForm"))[:300]
    except Exception:
        return ""
INVALID = "[aria-invalid=true]:visible, .error:visible, .field-error:visible, [class*=error-message i]:visible, [class*=invalid-feedback i]:visible, [class*=has-error i]:visible"
ERROR_WORDS = re.compile(r"\b(error|invalid|required|fail|missing|please (fill|enter|select|upload|complete)|not valid|"
                         r"pflichtfeld|erforderlich|verplicht|obligatorio|obligatoire|pakollinen|必須)\b", re.I)
OK_WORDS = re.compile(r"success|sent|received|submitted|thank|erfolgreich|gesendet|verzonden|enviad|envoyé|lähetetty|完了", re.I)


def page_state(current, frame) -> dict:
    """What the page shows in the way of complaints right now: the count of invalid fields,
    the feedback texts, and the page's error phrases. Taken before Submit and compared
    after, so a static "* indicates a required field" note is never read as a rejection."""
    try:
        invalid = frame.locator(INVALID).count()
    except Exception:
        invalid = 0
    try:
        said = {t.strip() for f in _frames(current)[:3] for t in f.locator(FEEDBACK).all_inner_texts()[:12] if t.strip()}
    except Exception:
        said = set()
    body = _body(current)
    return {"invalid": invalid, "said": said, "page_errors": set(m.group(0).lower() for m in PAGE_ERROR.finditer(body)), "body": body}


def _after_submit(current, frame, before: dict | None = None, why: dict | None = None, wait_s: float = 12.0) -> str:
    """What the page says after Submit was pressed, polled for `wait_s`:
    "submitted" (a thank-you text, or a success toast), "errors" (a NEW field complaint -
    one that was not on the page before Submit), "captcha", "gone" (the form vanished,
    nothing said), or "" (the form is still there). `why` receives the evidence."""
    before = before or {"invalid": 0, "said": set(), "page_errors": set()}
    why = why if why is not None else {}
    end = time.monotonic() + wait_s
    complaint = ""
    while True:
        if captcha(current):
            return "captcha"
        now = page_state(current, frame)
        body = now["body"]
        if THANKS.search(body) or re.search(r"thank|confirm|success|submitted", current.url or "", re.I):
            return "submitted"
        said = " ".join(sorted(now["said"]))
        new_said = " ".join(sorted(now["said"] - before["said"]))
        if said and THANKS.search(said):
            return "submitted"
        # a toast that says the application went ("Application sent!") - not a static
        # "our success stories" block that happens to carry a success-ish class
        if new_said and OK_WORDS.search(new_said) and not ERROR_WORDS.search(new_said) \
                and re.search(r"applic|apply|applied|submission|form|resume|candidat|bewerbung|sollicitatie|hakemus", new_said, re.I):
            return "submitted"
        new_errors = now["page_errors"] - before["page_errors"]
        if now["invalid"] > before["invalid"]:
            complaint = complaint or f"{now['invalid'] - before['invalid']} field(s) marked invalid"
        elif new_said and ERROR_WORDS.search(new_said):
            complaint = complaint or "the page said: " + new_said[:120]
        elif new_errors:
            complaint = complaint or "the page said: " + "; ".join(sorted(new_errors))[:120]
        if complaint and time.monotonic() >= end - wait_s / 2:
            # a complaint, and half the wait spent with no thank-you after it: a rejection
            why["complaint"] = complaint
            return "errors"
        try:
            gone = frame.locator("[data-ca]").count() and frame.locator("[data-ca]:visible").count() == 0
        except Exception:
            gone = False
        if gone and not complaint:
            return "gone"
        if time.monotonic() >= end:
            if complaint:
                why["complaint"] = complaint
                return "errors"
            return ""
        current.wait_for_timeout(1000)


PICKER_BUTTON = re.compile(r"^\W*(add file|upload (your |a )?(resume|cv|file)|attach (your |a )?(resume|cv|file)|choose file|select file)", re.I)
PICKER_BROWSE = re.compile(r"^\W*(browse|select files? from (your )?(device|computer)|upload|choose files?|from (your )?(device|computer))", re.I)


def upload_via_picker(page, resume: str) -> int:
    """Resume boxes that are a button, not an <input type=file>: Google Forms' "Add file"
    opens Drive's picker, whose Browse opens the OS file chooser - answered here with the
    resume. Returns how many files went up."""
    done = 0
    for frame in _frames(page)[:3]:
        try:
            buttons = frame.get_by_role("button", name=PICKER_BUTTON).all()[:3]
        except Exception:
            continue
        for btn in buttons:
            try:
                if not btn.is_visible(timeout=500):
                    continue
                human.click(page, btn, timeout=4000)
                page.wait_for_timeout(2500)
                picker = next((f for f in page.frames if "picker" in (f.url or "")), None)
                with page.expect_file_chooser(timeout=8000) as chooser:
                    if not _click_text(picker or page, PICKER_BROWSE):
                        raise RuntimeError("no Browse button in the picker")
                chooser.value.set_files(resume)
                page.wait_for_timeout(5000)          # the upload itself
                done += 1
            except Exception as exc:  # noqa: BLE001 - the form then stops at its required question, as before
                log.debug("picker upload failed: %s", exc)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
    return done


APPLIED_JS = r"""
(() => {
  // The posting's own Apply control now says "Applied": a button (or a disabled control)
  // in the page's main content. Not a link - Wellfound's sidebar has a link called
  // "Applied" (your applications list), which is how 10 postings were wrongly recorded.
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(e).visibility !== 'hidden'; };
  const txt = e => (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
  const re = /^\W*(applied|application (sent|submitted)|you('ve| have) applied|already applied|bereits beworben|ya aplicaste|応募済み)\b/i;
  // Naukri's badge is a <div class="already-applied">, hence the class selector
  for (const e of document.querySelectorAll('button, [role=button], input[type=submit], input[type=button], [aria-disabled=true], [disabled], [class*=applied i]')) {
    if (!vis(e) || !re.test(txt(e))) continue;
    if (e.tagName === 'A' || e.closest('a[href], nav, aside, header, footer, [role=navigation], [role=menu], [class*=sidebar i], [class*=nav i]')) continue;
    return txt(e).slice(0, 40);
  }
  return '';
})()
"""


def board_applied(page) -> bool:
    """The board itself says the application is in (one-click applies on Instahyre,
    Hirist, Cutshort, Wellfound ...): the posting's Apply button now reads "Applied",
    or a thank-you line appeared. Links and navigation never count."""
    for frame in _frames(page)[:3]:
        try:
            if frame.evaluate(APPLIED_JS):
                return True
        except Exception:
            continue
    return bool(THANKS.search(_body(page)))


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
                human.click(page, el, timeout=3000)
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
                    capture: dict | None = None, offsite_click=None, prefill=None, tailor=None,
                    platforms: bool | None = None) -> tuple[str, str]:
    """Apply starting from `page`, which shows the posting.

    `offsite_click` is a callable that presses the board's own offsite button
    (Naukri / LinkedIn); without it the posting's own Apply button is used when
    the form is not on the page yet. `prefill(page) -> int` gets the form
    first when given (Simplify's autofill, see simplify.py); fill_form then
    only answers what it left empty. Returns (status, note); extra tabs opened
    here are closed before returning. `platforms` overrides the per-platform
    switches (platform_switch.py): False stops before any apply on a job
    platform, True allows every one, None (default) asks the switch for the
    platform the form is on.
    """
    capture = capture if capture is not None else {}
    lacking = missing_details(who)
    if lacking and prefill is None:
        return "career-incomplete", f"set applicant.{', applicant.'.join(lacking)} in jobs.yaml"
    opened = set()
    current = page
    tailored_note = ""

    def platform_ok(url: str) -> bool:
        if platforms is not None:
            return bool(platforms)
        return platform_switch.allowed(url)

    try:
        dismiss_overlays(page)
        jd_text = job.get("description") or _body(page)      # the posting, for the tailored resume
        job = dict(job, description=jd_text[:4000])           # ...and for answers written about this job
        if CLOSED.search(_body(page)):
            return "closed", "the listing no longer accepts applications"
        if offsite_click is not None:
            if board_applied(page):
                # the board's page shows "Applied" (an earlier application, by hand or by us)
                return "closed", "the job page already shows Applied"
            nxt = _follow_click(page, offsite_click)
            if nxt is None:
                if CLOSED.search(_body(page)):
                    return "closed", "the listing no longer accepts applications"
                if board_applied(page):
                    return "closed", "the job page already shows Applied"
                # the board's button selector missed: the labelled control, by its text
                nxt = _follow_click(page, lambda: _click_text(page, OFFSITE_TEXT))
            if nxt is None:
                shot = _shot(page, job, "-nobutton")
                seen = _apply_words(page)
                return "career-error", ("could not press the company-site Apply button" +
                                        (f" (buttons seen: {seen})" if seen else " (no apply-worded button on the page)") +
                                        (f" ({shot})" if shot else ""))
            current = nxt
        if current is not page:
            opened.add(current)
        host = _needs_account(current.url)
        if host:
            return "login-required", f"{host} needs its own account (sign in once with: python main.py --platform-login)"

        total_filled = 0
        ats_tried = outbound_tried = waited = blank_waited = scrolled = pressed_apply = False
        submitted_pages = 0
        for step in range(12):
            if CLOSED.search(_body(current)):
                return "closed", "the listing no longer accepts applications"
            # a hosted application system: go straight to its form page
            form_url = None if ats_tried else _ats_form_url(current.url)
            if form_url and form_url != current.url:
                ats_tried = True
                current.goto(form_url, wait_until="domcontentloaded", timeout=45000)
                current.wait_for_timeout(2500)
            dismiss_overlays(current)
            wall = login_wall(current, text=False)
            if wall:
                _shot(current, job, "-login")
                return "login-required", wall
            kind = captcha(current)
            if kind:
                _shot(current, job, "-captcha", full=True)
                return "captcha", f"the form has a CAPTCHA ({kind}) - apply by hand"
            on_board = platform_host(current.url)
            if on_board and offsite_click is None and board_applied(current):
                if step == 0 or total_filled == 0 and not pressed_apply:
                    # the posting already shows "Applied" before anything was pressed: applied earlier
                    return "closed", f"the posting on {on_board} already shows Applied ({_shot(current, job, '-already')})"
                # a one-click apply on the board itself went through
                return "submitted", f"applied on {on_board} with your saved login ({_shot(current, job, '-done')})"
            frame, fields = _form_frame(current)
            if aggregator_host(current.url):
                fields = []                      # an aggregator's page is never the application
            # A dialog that opened from the Apply button (Wellfound's "Send application" box: one
            # message field) is the form even with a single field.
            in_dialog = any(re.search(r"dialog|modal", f.get("ctx") or "", re.I) for f in fields)
            fillable = [f for f in fields if f["type"] not in ("checkbox", "radio")]
            if in_dialog and pressed_apply and len(fillable) == 1:
                fillable = fillable * 2          # counts as a form below
            if len(fillable) >= 2 and not looks_like_application(fields, _form_buttons(frame)):
                fillable = []                    # a search box and an alert e-mail, or a contact form - not the application
            if len(fillable) >= 2 and on_board and not platform_ok(current.url):
                return "platform-off", f"the form is on {on_board} - {platform_switch.off_note(current.url)}"
            if len(fillable) < 2:
                if total_filled:
                    break               # submitted a page and no further form: check for a thank-you
                wall = login_wall(current)
                if wall:
                    _shot(current, job, "-login")
                    return "login-required", wall
                if not waited and not aggregator_host(current.url):
                    waited = True       # a slow single-page app: its form may still be rendering
                    current.wait_for_timeout(4000)
                    continue
                if not blank_waited and len(_body(current).strip()) < 200:
                    # still a blank page (Accenture's careers app took 10+ s): give it a real chance
                    blank_waited = True
                    try:
                        current.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    current.wait_for_timeout(5000)
                    continue
                if on_board and on_board not in _host(page.url) and not platform_ok(current.url) \
                        and not aggregator_host(current.url):
                    # a board that applies on its own site, reached from elsewhere, and its switch is off
                    return "platform-off", f"{on_board} applies on its own site - {platform_switch.off_note(current.url)}"
                page_now = current
                nxt = None
                if aggregator_host(current.url) and not outbound_tried:
                    # an aggregator's listing: its link out to the employer first
                    outbound_tried = True
                    target = _outbound_apply(current)
                    if target:
                        current.goto(target, wait_until="domcontentloaded", timeout=45000)
                        current.wait_for_timeout(2500)
                        _leave_linkedin(current)
                        nxt = current
                if nxt is None:
                    human.wander(current)
                    nxt = _follow_click(current, lambda: _click_apply(page_now))
                    pressed_apply = pressed_apply or nxt is not None
                if nxt is None and not outbound_tried:
                    outbound_tried = True
                    target = _outbound_apply(current)
                    if target:
                        current.goto(target, wait_until="domcontentloaded", timeout=45000)
                        current.wait_for_timeout(2500)
                        _leave_linkedin(current)
                        nxt = current
                if nxt is None and not scrolled:
                    # a form or an Apply button further down that only renders once scrolled to
                    scrolled = True
                    for _ in range(5):
                        try:
                            current.mouse.wheel(0, random.uniform(500, 900))
                        except Exception:
                            break
                        current.wait_for_timeout(random.uniform(500, 900))
                    continue
                if nxt is None:
                    shot = _shot(current, job, "-noform", full=True)
                    seen = _apply_words(current)
                    return "no-form", ("no application form or Apply button found on the company page" +
                                       (f" (buttons seen: {seen})" if seen else "") + (f" ({shot})" if shot else ""))
                if nxt is not current:
                    opened.add(nxt)
                current = nxt
                host = _needs_account(current.url)
                if host:
                    return "login-required", f"the Apply button leads to {host}, which needs its own account"
                continue

            if tailor is not None and not tailored_note:
                # a resume arranged for this job, uploaded instead of the generic one (naukri/jobs/tailor.py)
                tailored_note = " · generic resume"
                try:
                    path, info = tailor(job, jd_text if len(jd_text) > 300 else _body(current))
                    if path:
                        who = dict(who, resume=str(path))
                        capture["tailored_resume"] = info
                        tailored_note = f" · tailored resume, {info.get('match')}% of the job's skills"
                except Exception as exc:  # noqa: BLE001 - the generic resume still works
                    log.debug("tailor failed: %s", exc)
            prefilled = 0
            if prefill is not None:
                try:
                    prefilled = int(prefill(current) or 0)
                except Exception as exc:  # noqa: BLE001 - Simplify is a helper, not a requirement
                    log.debug("prefill failed: %s", exc)
                frame, fields = _form_frame(current)     # rescan: values and pages may have changed
            filled, blocked = fill_form(frame, fields, who, facts, job, capture)
            total_filled += filled + prefilled
            if who.get("resume") and not any(f["type"] == "file" for f in fields):
                # no file box on the page: a Google Form's "Add file" button (the Drive picker) instead?
                total_filled += upload_via_picker(current, who["resume"])
            if blocked:
                capture["blocked_all"] = blocked
                shot = _shot(current, job, "-incomplete")
                return "career-incomplete", f"cannot answer: {'; '.join(b[:120] for b in blocked[:3])} ({shot})"
            if dry_run:
                return "would-apply", f"{total_filled} field(s) filled; dry run ({_shot(current, job, '-dry')})"

            before = page_state(current, frame)
            pressed = _press_submit(frame, current)
            if pressed is None:
                return "career-incomplete", f"filled {total_filled} field(s) but found no Submit button ({_shot(current, job, '-nosubmit', full=True)})"
            submitted_pages += 1
            why: dict = {}
            result = _after_submit(current, frame, before, why)
            if result == "captcha":
                _shot(current, job, "-captcha", full=True)
                return "captcha", f"a CAPTCHA appeared on submit ({captcha(current) or 'challenge'}) - apply by hand"
            if result == "submitted":
                return "submitted", f"{total_filled} field(s) filled and submitted{tailored_note} ({_shot(current, job, '-done')})"
            if result == "errors":
                return "career-incomplete", f"the form rejected some answers - {why.get('complaint', 'unclear')} ({_shot(current, job, '-errors', full=True)})"
            if result == "gone" and pressed == "submit":
                # the form closed and nothing complained: the next scan finds no form and settles below
                current.wait_for_timeout(2500)
            # Otherwise a multi-page form moved on: fill the next page.
        body = _body(current)
        if THANKS.search(body):
            return "submitted", f"{total_filled} field(s) filled and submitted{tailored_note} ({_shot(current, job, '-done')})"
        frame, fields = _form_frame(current)
        remaining = [f for f in fields if f["type"] not in ("checkbox", "radio")]
        if PAGE_ERROR.search(body):
            return "career-incomplete", f"the site said the submission failed ({_shot(current, job, '-errors', full=True)})"
        if submitted_pages and len(remaining) < 2:
            # Submit was pressed, the form itself is gone and no error appeared: the site
            # just has no thank-you text (Designoweb, several Indian career pages). A form
            # still standing there - filled or not - is NOT that.
            return "submitted", (f"{total_filled} field(s) filled and submitted - form closed, no thank-you text"
                                 f"{tailored_note} ({_shot(current, job, '-done', full=True)})")
        return "career-unconfirmed", f"pressed Submit, no confirmation seen{tailored_note} ({_shot(current, job, '-after', full=True)})"
    except Exception as exc:  # noqa: BLE001
        return "career-error", str(exc)[:160]
    finally:
        for extra in opened:
            try:
                if extra is not page:
                    extra.close()
            except Exception:
                pass


OFFSITE_TEXT = re.compile(r"^\W*(apply (on|via|at) (the )?(company|employer)('s)? ?(site|website|page)?|"
                          r"apply on company|company site|apply externally|apply on website)", re.I)


def _apply_words(page) -> str:
    """The apply-worded controls on the page, for the note when none could be pressed."""
    seen = []
    for frame in _frames(page)[:3]:
        try:
            for t in frame.locator("button, a, [role=button], input[type=submit]").all_inner_texts()[:200]:
                t = re.sub(r"\s+", " ", t or "").strip()
                if t and re.search(r"apply|bewerb|postul|solicit|candidat|応募|สมัคร", t, re.I) and t not in seen:
                    seen.append(t[:40])
        except Exception:
            continue
    return "; ".join(seen[:6])


# Ledger notes of company-site failures the applier has since been fixed for; release_failed()
# puts these postings back in line once.
RELEASABLE = re.compile(r"no application form or Apply button|found no Submit button|no confirmation seen|"
                        r"page did not open|could not press the company-site Apply|needs its own account|"
                        r"platform auto-apply is off|the form rejected some answers|Target (page|closed)|"
                        r"the form has a CAPTCHA|"
                        r"Timeout \d+ms|net::ERR", re.I)


def release_failed(days: int = 30, dry_run: bool = False) -> dict:
    """Put back in line every posting the applier gave up on for a reason that is fixed now.

    Worldwide-board postings ("web:" keys) are dropped from the ledger, so the
    next round's search lists them again and applies; Naukri / LinkedIn ones
    get their "company site: " mark replaced by "retry requested: ", which is
    what makes autoapply try the career site once more. A "needs its own
    account" note is released only when that host is signed in now
    (data/platform_logins.json) or was never a login host.
    """
    from datetime import date, timedelta

    from .ledger import Ledger

    ledger = Ledger()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    counts = {"web": 0, "naukri": 0, "linkedin": 0, "kept": 0}
    for key, entry in list(ledger.entries.items()):
        note = str(entry.get("note") or "")
        if entry.get("status") != "offsite" or str(entry.get("at", ""))[:10] < cutoff or not RELEASABLE.search(note):
            continue
        url = entry.get("url") or ""
        if "needs its own account" in note:
            if not key.startswith("web:") or _needs_account(url):
                counts["kept"] += 1
                continue
        if int(entry.get("released") or 0) >= 2:
            # released twice already and still failing: a real wall, not a bug - stop spending runs on it
            counts["kept"] += 1
            continue
        if key.startswith("web:"):
            if not dry_run:
                del ledger.entries[key]
            counts["web"] += 1
        else:
            if not dry_run:
                entry["note"] = "retry requested: " + (note[len(TRIED):] if note.startswith(TRIED) else note)
                entry["released"] = int(entry.get("released") or 0) + 1
            counts["linkedin" if key.startswith("linkedin:") else "naukri"] += 1
    if not dry_run:
        ledger.save()
    return counts

def transient(status: str, note: str) -> bool:
    """A failure worth another go next run (network down, a timeout) - not recorded as tried."""
    if status == "platform-off":
        return True     # nothing was tried; the switch turned on picks it up
    return status == "career-error" and bool(re.search(r"net::ERR|Timeout|timed out|Target closed|has been closed", note or "", re.I))


def ledger_status(status: str) -> str:
    """How an outcome is stored: a submission counts as applied, a closed listing
    as skipped; everything else is finished on this site ("offsite") so it is not
    retried every run."""
    return {"submitted": "applied", "closed": "skipped"}.get(status, "offsite")


def queue_status(status: str) -> str:
    return {"submitted": "submitted", "would-apply": "queued", "platform-off": "queued",
            "closed": "skipped", "already": "skipped"}.get(status, "manual")


def main(argv=None) -> int:
    import argparse
    from playwright.sync_api import sync_playwright

    from . import answers as answers_mod, config as config_mod, questions
    from ..session import launch_browser, new_context

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="a posting to try")
    ap.add_argument("--submit", action="store_true", help="really submit (default: fill only)")
    ap.add_argument("--show", action="store_true", help="visible browser")
    ap.add_argument("--release", action="store_true",
                    help="put every company-site posting the applier gave up on (for a reason fixed since) back in line, then exit")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run", help="with --release: only count")
    a = ap.parse_args(argv)
    if a.release:
        counts = release_failed(dry_run=a.dry_run)
        print("released%s: %d worldwide-board, %d Naukri, %d LinkedIn posting(s); %d kept (host still needs a login)"
              % (" (dry run)" if a.dry_run else "", counts["web"], counts["naukri"], counts["linkedin"], counts["kept"]))
        return 0
    if not a.url:
        ap.error("a posting URL is needed (or --release)")
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
