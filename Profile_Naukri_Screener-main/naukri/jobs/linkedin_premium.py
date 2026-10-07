"""LinkedIn Premium, used to the full for every day it is paid for (data/premium/premium.yaml: `until`).

    python -m naukri.jobs.linkedin_premium --once            one pass now (headless), then the day's report
    python -m naukri.jobs.linkedin_premium --loop            a pass every `every_minutes` until `until`
    python -m naukri.jobs.linkedin_premium --once --show     with a visible browser
    python -m naukri.jobs.linkedin_premium --once --dry-run  read everything, apply to nothing, like nothing
    python -m naukri.jobs.linkedin_premium --draft           only write today's post draft (no browser)
    python -m naukri.jobs.linkedin_premium --report          only rebuild today's report from the saved state

One pass, in order, every step on its own so a broken one never stops the rest:

  1. REACH      the numbers on your own profile (profile views, post impressions, search
                appearances) are read and kept day by day, so the report shows the trend.
  2. VIEWERS    Premium's full "who viewed your profile" list is read. Every new viewer is
                remembered; recruiters / talent / hiring people among them become LEADS, each with
                a drafted connection note. Nothing is sent unless `connect_per_day` > 0 - then
                that many recruiter-viewers a day get a connection request with the note.
  3. JOBS       Premium's "Top applicant" collection (jobs LinkedIn ranks you in the top of),
                plus fresh (24 h) searches for your roles in India and in the countries you want to
                move to. Each candidate's page is opened (at most `open_per_pass`): the Premium
                applicant insight ("you'd be a top applicant", the applicant count), the hiring
                team named on the page, and - for jobs abroad - whether the posting offers visa
                sponsorship or relocation. Everything is ranked; the best Easy Apply postings are
                applied to through the same walker, answers and daily cap as the rest of the
                project (naukri/jobs/linkedin_apply.py), `apply_per_day` of them a day. Offsite
                ones are listed for you, best first.
  4. INMAILS    for the best jobs whose hiring manager / recruiter is named, a short InMail is
                drafted (under 80 words) and put in the report with the person's link. You have 5
                InMail credits a month: sending stays yours.
  5. LIKES      at least one post a day is liked (`likes_per_day`): the freshest hiring posts for
                your roles from data/posts/linkedin_posts.json (the hiring-posts watcher), so the
                like lands with a recruiter who is hiring right now.
  6. DRAFT      one post a day is written for you to post yourself, from a rotation of topics drawn
                from your resume, by the local model when it is there and from a template when it
                is not: data/premium/drafts/<date>.md (and TODAY.md).
  7. REPORT     data/premium/daily/<date>.md, rebuilt after every pass (LATEST.md is a copy):
                days of Premium left, what was applied to, the leads, the InMail drafts, the
                offsite jobs to apply to yourself, the abroad checklist. Log: logs/linkedin_premium.log.

Pacing: 20-40 page loads a pass, a pass every 4 hours by default, human gaps between pages. The
Easy Apply cap in jobs.yaml (`linkedin_max_applies_per_day`) and LinkedIn's own daily limit
(linkedin_limit.py) are shared with every other run on this PC.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

log = logging.getLogger("naukri.jobs.linkedin_premium")

ROOT = Path(__file__).resolve().parent.parent.parent
DIR = ROOT / "data" / "premium"
CONFIG_PATH = DIR / "premium.yaml"
STATE_PATH = DIR / "state.json"
DRAFTS_DIR = DIR / "drafts"
DAILY_DIR = DIR / "daily"
LOG_PATH = ROOT / "logs" / "linkedin_premium.log"
POSTS_STORE = ROOT / "data" / "posts" / "linkedin_posts.json"

TOP_APPLICANT_URL = "https://www.linkedin.com/jobs/collections/top-applicant/"
RECOMMENDED_URL = "https://www.linkedin.com/jobs/collections/recommended/"
VIEWERS_URL = "https://www.linkedin.com/analytics/profile-views/"
ME_URL = "https://www.linkedin.com/in/me/"

DEFAULTS = {
    "until": "2026-10-30",
    "every_minutes": 240,
    "roles": ["Software Engineer", "Backend Engineer", "Backend Developer", "Full Stack Developer" ,"Full Stack Engineer" , "Frontend Engineer" , "Frontend Developer" , "SDE" , "SWE"],
    "abroad_countries": ["Germany", "Netherlands", "Ireland", "United Kingdom", "United States" , "Canada", "Singapore",
                         "United Arab Emirates", "Australia", "Sweden", "Switzerland", "Japan", "Portugal" , "NYC" , "New York" , "Chicago"],
    "include_india": True,
    "remote_worldwide": True,
    "apply_per_day": 80,
    "open_per_pass": 14,
    "abroad_searches_per_pass": 60,
    "india_searches_per_pass": 12,
    "likes_per_day": 2,
    "connect_per_day": 10,
    "draft_per_day": 2,
    "exclude_senior": True,
    "max_experience_years": 2,
    "hashtags": ["#SoftwareEngineer", "#Backend", "#Java", "#Kafka", "#OpenToWork", "#Relocation", "#Frontend" , "#SoftwareDeveloper" , "#SDE" , "#SWE" ,"#Software Engineer", "#BackendEngineer", "#BackendDeveloper", "#FullStackDeveloper" ,"#FullStackEngineer" , "#FrontendEngineer" , "#FrontendDeveloper" , "#SDE" , "#SWE" ],
}

# ----------------------------------------------------------------------------- reading text

RECRUITER_RX = re.compile(
    r"\b(recruit|talent|hiring|hr\b|human resources|people (?:ops|operations|partner)|sourc(?:er|ing)|staffing|"
    r"head ?hunt|acquisition|hiring manager|engineering manager|cto\b|vp engineering|head of engineering|"
    r"founder|co-?founder|tech lead|team lead)", re.I)
SENIOR_RX = re.compile(r"\b(senior|\bsr\.?\b|lead\b|principal|staff|architect|manager|head of|director|\bvp\b|"
                       r"chief|distinguished|fellow|iii\b|iv\b)", re.I)
ROLE_RX = re.compile(r"\b(software|backend|back-end|full[- ]?stack|java|spring|kafka|developer|engineer|sde\b|swe\b|"
                     r"platform|distributed|microservices|api|\.net|c#|node|python|react|angular)", re.I)
TOP_APPLICANT_RX = re.compile(r"you(?:'|’)?d be a top applicant|you are a top applicant|top applicant", re.I)
APPLICANTS_RX = re.compile(r"(?:over\s+)?(\d[\d,]*)\s*\+?\s*(?:applicants|people clicked apply|clicked apply)", re.I)
POSTED_RX = re.compile(r"(?:reposted|posted)\s+(\d+)\s+(minute|hour|day|week|month)s?\s+ago", re.I)
EXP_RX = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b", re.I)
REACH_RX = {
    "profile_views": re.compile(r"(\d[\d,]*)\s+profile views?", re.I),
    "post_impressions": re.compile(r"(\d[\d,]*)\s+post impressions?", re.I),
    "search_appearances": re.compile(r"(\d[\d,]*)\s+search appearances?", re.I),
}
INDIA_RX = re.compile(r"\b(india|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|gurgaon|gurugram|noida|delhi|kolkata|"
                      r"ahmedabad|jaipur|indore|kochi|chandigarh|remote)\b", re.I)


def _int(s) -> int | None:
    try:
        return int(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def clean_headline(text: str) -> str:
    """'• 2nd | Senior Tech Recruiter | Viewed 2h ago' -> 'Senior Tech Recruiter'."""
    parts = [p.strip() for p in (text or "").split("|")]
    parts = [p for p in parts if p and not re.match(r"^(•\s*)?(1st|2nd|3rd|\d+(st|nd|rd|th))\b", p)
             and not re.match(r"^(viewed|you both|mutual)\b", p, re.I)]
    return " | ".join(parts)[:220]


def is_recruiter(headline: str) -> bool:
    """Would this viewer plausibly hire or refer you? Recruiters, HR, hiring managers, founders, leads."""
    return bool(RECRUITER_RX.search(headline or ""))


def applicants_of(text: str) -> int | None:
    m = APPLICANTS_RX.search(text or "")
    if not m:
        return None
    n = _int(m.group(1))
    if n is not None and re.search(r"over\s+%s" % re.escape(m.group(1)), text, re.I):
        n += 1
    return n


def posted_hours(text: str) -> float | None:
    m = POSTED_RX.search(text or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * {"minute": 1 / 60, "hour": 1, "day": 24, "week": 168, "month": 720}[unit]


def years_asked(text: str) -> int | None:
    """The smallest 'N years' / 'N-M years' figure a posting states, or None."""
    lows = []
    for m in EXP_RX.finditer(text or ""):
        lo = int(m.group(1))
        if 0 <= lo <= 20:
            lows.append(lo)
    return min(lows) if lows else None


def is_abroad(location: str) -> bool:
    return not INDIA_RX.search(location or "")


def _relocation_module():
    """job-hunt's relocation / sponsorship reader, when that checkout is next door."""
    scripts = ROOT.parent / "job-hunt" / "scripts"
    if scripts.is_dir() and str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from jobbot.careers import relocation  # type: ignore
        return relocation
    except Exception:  # noqa: BLE001
        return None


def _localai():
    scripts = ROOT.parent / "job-hunt" / "scripts"
    if scripts.is_dir() and str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from jobbot import localai  # type: ignore
        return localai if localai.available("llm") else None
    except Exception:  # noqa: BLE001
        return None


def sponsorship_of(title: str, text: str) -> dict:
    """{"relocation": yes|no|unclear, "visa": yes|no|unclear, "evidence": ...} from the posting's words."""
    mod = _relocation_module()
    if mod is not None:
        try:
            out = mod.assess(title, text)
            return {"relocation": out.get("relocation", "unclear"), "visa": out.get("visa", "unclear"),
                    "evidence": (out.get("evidence") or "")[:200]}
        except Exception as exc:  # noqa: BLE001
            log.debug("relocation.assess failed: %s", exc)
    t = text or ""
    visa = "yes" if re.search(r"visa sponsorship|sponsor(?:ship)? (?:is )?(?:available|provided|offered)|we sponsor", t, re.I) else \
        "no" if re.search(r"no (?:visa )?sponsorship|unable to sponsor|cannot sponsor|must (?:already )?(?:have|hold) the right to work|"
                          r"without sponsorship|not able to (?:offer|provide) (?:visa )?sponsorship", t, re.I) else "unclear"
    reloc = "yes" if re.search(r"relocation (?:package|support|assistance|bonus)|we(?:'ll| will) (?:help you )?relocate", t, re.I) else "unclear"
    return {"relocation": reloc, "visa": visa, "evidence": ""}


# ----------------------------------------------------------------------------- ranking

def rank(card: dict, info: dict, cfg: dict) -> tuple[int, list[str]]:
    """Score one posting from its card and its inspected page. Higher is better; <= 0 means skip."""
    score, why = 0, []
    title = card.get("title") or ""
    if cfg.get("exclude_senior", True) and SENIOR_RX.search(title):
        return -100, ["senior title"]
    if not ROLE_RX.search(title):
        score -= 15
        why.append("title off-role")
    else:
        score += 10
    if info.get("top_applicant"):
        score += 40
        why.append("top applicant")
    if card.get("easy_apply"):
        score += 15
        why.append("easy apply")
    n = info.get("applicants")
    if n is not None:
        if n < 25:
            score += 15
            why.append(f"{n} applicants")
        elif n < 100:
            score += 8
            why.append(f"{n} applicants")
        else:
            score -= 5
            why.append(f"{n}+ applicants")
    h = info.get("posted_hours")
    if h is not None:
        if h <= 6:
            score += 15
            why.append("posted <6h")
        elif h <= 24:
            score += 10
            why.append("posted <24h")
        elif h > 168:
            score -= 10
    y = info.get("years_asked")
    if y is not None and y > int(cfg.get("max_experience_years", 4)):
        return -50, [f"asks {y}+ years"]
    if info.get("abroad"):
        sp = info.get("sponsorship") or {}
        if sp.get("visa") == "yes":
            score += 25
            why.append("visa sponsorship")
        elif sp.get("visa") == "no":
            score -= 30
            why.append("no sponsorship")
        if sp.get("relocation") == "yes":
            score += 15
            why.append("relocation offered")
        if info.get("remote"):
            score += 5
            why.append("remote")
    if "exclude" in info:
        return -100, [info["exclude"]]
    return score, why


# ----------------------------------------------------------------------------- state and config

def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = dict(DEFAULTS)
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if v is not None})
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("premium.yaml not read (%s); defaults used", exc)
    return cfg


def load_state(path: Path = STATE_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def today_key(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


def day(state: dict, now: datetime | None = None) -> dict:
    d = state.setdefault("days", {}).setdefault(today_key(now), {})
    d.setdefault("passes", 0)
    for k in ("applied", "liked", "connected", "drafted", "viewers_new", "opened"):
        d.setdefault(k, 0)
    for k in ("applied_jobs", "leads", "inmails", "offsite", "liked_posts", "errors", "skipped"):
        d.setdefault(k, [])
    return d


def days_left(cfg: dict, today: date | None = None) -> int:
    try:
        end = date.fromisoformat(str(cfg.get("until")))
    except (TypeError, ValueError):
        end = date(2026, 10, 30)
    return (end - (today or date.today())).days


def premium_over(cfg: dict, today: date | None = None) -> bool:
    return days_left(cfg, today) < 0


def today_linkedin_applied() -> int:
    """Easy Apply submissions made today by every run on this PC (shared ledger)."""
    try:
        from . import applications
        today = today_key()
        return sum(1 for e in applications.load()
                   if e.get("board") == "linkedin" and e.get("status") == "applied"
                   and not e.get("dry_run") and str(e.get("at", "")).startswith(today))
    except Exception as exc:  # noqa: BLE001
        log.debug("ledger not read: %s", exc)
        return 0


def apply_budget(cfg: dict, d: dict, daily_cap: int, applied_today_all: int) -> int:
    """How many Easy Applies this pass may still make: the module's own share, within the PC-wide cap."""
    own = int(cfg.get("apply_per_day", 8)) - int(d.get("applied", 0))
    shared = int(daily_cap) - int(applied_today_all)
    return max(0, min(own, shared))


def already_tried(job_id: str) -> bool:
    try:
        from . import applications
        return any(str(e.get("job_id")) == str(job_id) and e.get("status") in ("applied", "already", "questionnaire", "offsite")
                   for e in applications.load())
    except Exception:  # noqa: BLE001
        return False


# ----------------------------------------------------------------------------- the browser steps

def _goto(page, url: str, settle: float = 4.0) -> bool:
    for attempt in (1, 2):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(settle * 1000 + random.uniform(300, 1500))
            return True
        except Exception as exc:  # noqa: BLE001
            if attempt == 1 and any(e in str(exc) for e in ("ERR_", "Timeout")):
                time.sleep(random.uniform(15, 30))
                continue
            log.warning("could not open %s: %s", url, str(exc)[:140])
    return False


def _body(page, limit: int = 12000) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)[:limit]
    except Exception:  # noqa: BLE001
        return ""


def _pause(lo=3.0, hi=7.0) -> None:
    time.sleep(random.uniform(lo, hi))


def read_reach(page) -> dict:
    """profile views / post impressions / search appearances from your own profile's analytics strip."""
    out: dict = {}
    if not _goto(page, ME_URL):
        return out
    text = _body(page)
    for key, rx in REACH_RX.items():
        m = rx.search(text)
        if m:
            out[key] = _int(m.group(1))
    return out


_VIEWERS_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = []; const seen = new Set();
  document.querySelectorAll('a[href*="/in/"]').forEach(a => {
    const li = a.closest('li') || a.closest('article') || a.closest('div');
    if (!li) return;
    const href = (a.getAttribute('href') || '').split('?')[0];
    if (!href || seen.has(href)) return;
    const lines = (li.innerText || '').split('\n').map(norm).filter(Boolean);
    if (lines.length < 1) return;
    seen.add(href);
    out.push({url: href.startsWith('http') ? href : 'https://www.linkedin.com' + href,
              name: lines[0], headline: lines.slice(1, 4).join(' | ').slice(0, 220), text: lines.join(' | ').slice(0, 400)});
  });
  const body = document.body.innerText || '';
  const priv = (body.match(/private mode|linkedin member/gi) || []).length;
  return {viewers: out, private: priv};
}
"""


def read_viewers(page) -> dict:
    if not _goto(page, VIEWERS_URL, settle=5):
        return {"viewers": [], "private": 0}
    try:
        for _ in range(3):           # the list lazy-loads
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(random.uniform(900, 1600))
        data = page.evaluate(_VIEWERS_JS)
    except Exception as exc:  # noqa: BLE001
        log.warning("viewers not read: %s", str(exc)[:140])
        return {"viewers": [], "private": 0}
    # the page's own navigation and "people you may know" are not viewers
    keep = []
    for v in data.get("viewers", []):
        if not v.get("name") or re.search(r"^(you|me)$", v["name"], re.I) or "/in/me" in v["url"]:
            continue
        v["headline"] = clean_headline(v.get("headline"))
        keep.append(v)
    return {"viewers": keep[:60], "private": int(data.get("private") or 0)}


def connection_note(viewer: dict, me: dict) -> str:
    """Under 280 characters, LinkedIn's note limit is 300."""
    first = (viewer.get("name") or "").split(" ")[0] or "there"
    role = me.get("role", "Backend Software Engineer")
    stack = me.get("stack", "Java, Kafka, PostgreSQL, AWS")
    note = (f"Hi {first}, thanks for viewing my profile. I'm a {role} ({stack}, 2 yrs, 16x throughput wins in production) "
            f"and open to roles in India and abroad. Happy to connect in case a fit comes up.")
    return note[:280]


_CONNECT_BUTTON = "button[aria-label^='Invite'], button:has-text('Connect')"


def connect_with(page, viewer: dict, note: str) -> str:
    """Open the profile, Connect, Add a note, Send. Returns 'sent' | 'pending' | 'already' | 'no-button' | 'error'."""
    from . import human
    if not _goto(page, viewer["url"], settle=4):
        return "error"
    body = _body(page, 4000)
    if re.search(r"\bpending\b", body, re.I) and page.locator("button:has-text('Pending')").count():
        return "pending"
    if page.locator("button:has-text('Message')").count() and not page.locator(_CONNECT_BUTTON).count():
        # a 1st-degree connection has Message where Connect would be; "More" may hide Connect for 2nd
        more = page.locator("button:has-text('More')").first
        try:
            if more.count():
                human.click(page, more)
                page.wait_for_timeout(1200)
        except Exception:  # noqa: BLE001
            pass
    btn = page.locator(_CONNECT_BUTTON).first
    try:
        if not btn.count():
            return "already" if page.locator("button:has-text('Message')").count() else "no-button"
        human.click(page, btn)
        page.wait_for_timeout(random.uniform(1500, 2500))
        add = page.locator("button:has-text('Add a note')").first
        if add.count():
            human.click(page, add)
            page.wait_for_timeout(random.uniform(900, 1500))
            box = page.locator("textarea[name='message'], textarea#custom-message, textarea").first
            human.type_into(page, box, note)
            page.wait_for_timeout(random.uniform(700, 1300))
        send = page.locator("button[aria-label='Send now'], button[aria-label='Send invitation'], button:has-text('Send')").first
        if not send.count():
            return "error"
        human.click(page, send)
        page.wait_for_timeout(random.uniform(1500, 2500))
        return "sent"
    except Exception as exc:  # noqa: BLE001
        log.warning("connect with %s failed: %s", viewer.get("name"), str(exc)[:140])
        return "error"


def cards_at(page, url: str, linkedin_mod) -> list[dict]:
    if not _goto(page, url, settle=5):
        return []
    try:
        linkedin_mod._load_all_cards(page)
        cards = page.evaluate(linkedin_mod._EXTRACT_JS) or []
    except Exception as exc:  # noqa: BLE001
        log.warning("cards not read at %s: %s", url, str(exc)[:140])
        return []
    return cards


_HIRING_TEAM_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const heads = Array.from(document.querySelectorAll('h2, h3, h4, span, div'))
    .filter(e => /meet the hiring team|hiring team|job poster|posted by/i.test(norm(e.innerText).slice(0, 40)) && e.children.length < 4);
  const out = []; const seen = new Set();
  for (const h of heads) {
    let sec = h; for (let i = 0; i < 4 && sec && sec.parentElement; i++) sec = sec.parentElement;
    sec.querySelectorAll('a[href*="/in/"]').forEach(a => {
      const href = (a.getAttribute('href') || '').split('?')[0];
      if (!href || seen.has(href)) return;
      const lines = norm(a.innerText).split(' | ');
      const card = a.closest('div');
      const txt = card ? (card.innerText || '').split('\n').map(norm).filter(Boolean) : [];
      seen.add(href);
      out.push({url: href.startsWith('http') ? href : 'https://www.linkedin.com' + href,
                name: txt[0] || lines[0] || '', headline: (txt.slice(1, 3).join(' | ')).slice(0, 160)});
    });
    if (out.length) break;
  }
  return out.slice(0, 3);
}
"""


def inspect_job(page, card: dict) -> dict:
    """Open the posting and read what Premium and the page say about it."""
    info: dict = {"abroad": is_abroad(card.get("location") or ""), "remote": bool(re.search(r"\bremote\b", card.get("location") or "", re.I))}
    if not _goto(page, card["url"], settle=4):
        info["exclude"] = "page did not open"
        return info
    text = _body(page)
    info["text"] = text[:6000]
    # LinkedIn's own "Top applicant" collection is the Premium ranking; the page's insight chip is not always in the text
    info["top_applicant"] = bool(TOP_APPLICANT_RX.search(text[:4000])) or card.get("source") == "top-applicant"
    info["applicants"] = applicants_of(text[:4000])
    info["posted_hours"] = posted_hours(text[:4000])
    info["years_asked"] = years_asked(text)
    if re.search(r"no longer accepting applications", text, re.I):
        info["exclude"] = "closed"
    try:
        info["hiring_team"] = [dict(h, headline=clean_headline(h.get("headline"))) for h in (page.evaluate(_HIRING_TEAM_JS) or [])]
    except Exception:  # noqa: BLE001
        info["hiring_team"] = []
    if info["abroad"]:
        info["sponsorship"] = sponsorship_of(card.get("title") or "", text)
    try:
        info["easy_apply"] = page.locator("button[aria-label*='Easy Apply' i], button:has-text('Easy Apply')").first.is_visible(timeout=2500)
    except Exception:  # noqa: BLE001
        info["easy_apply"] = bool(card.get("easy_apply"))
    return info


def job_urls_for_pass(cfg: dict, state: dict, linkedin_mod) -> list[tuple[str, str]]:
    """(label, url) pairs to read this pass: the Premium collections, then a rotating slice of the searches."""
    urls = [("top-applicant", TOP_APPLICANT_URL + "?f_TPR=r86400"), ("top-applicant", TOP_APPLICANT_URL)]
    roles = list(cfg.get("roles") or DEFAULTS["roles"])
    searches: list[tuple[str, str]] = []
    for country in cfg.get("abroad_countries") or []:
        for role in roles[:3]:
            searches.append((f"abroad:{country}", linkedin_mod.search_url(role, country, 1)))
    if cfg.get("remote_worldwide", True):
        for role in roles[:2]:
            searches.append(("remote", linkedin_mod.search_url(role, "Worldwide", 1, remote_only=True)))
    india: list[tuple[str, str]] = []
    if cfg.get("include_india", True):
        for role in roles:
            india.append(("india", linkedin_mod.search_url(role, "India", 1)))
    cur = int(state.get("search_cursor") or 0)
    n_ab = int(cfg.get("abroad_searches_per_pass", 6))
    if searches:
        urls += [searches[(cur + i) % len(searches)] for i in range(min(n_ab, len(searches)))]
        state["search_cursor"] = (cur + n_ab) % len(searches)
    cur_in = int(state.get("india_cursor") or 0)
    n_in = int(cfg.get("india_searches_per_pass", 2))
    if india:
        urls += [india[(cur_in + i) % len(india)] for i in range(min(n_in, len(india)))]
        state["india_cursor"] = (cur_in + n_in) % len(india)
    return urls


def inmail_draft(card: dict, person: dict, me: dict) -> str:
    """Under 80 words: the role, one proof line, one ask. The local model writes it when it can."""
    first = (person.get("name") or "").split(" ")[0] or "there"
    title, company = card.get("title") or "the role", card.get("company") or "your team"
    ai = _localai()
    if ai is not None:
        try:
            out = ai.ask(
                f"Write a LinkedIn InMail (max 75 words, plain text, no subject line, no placeholders) from the candidate below "
                f"to {person.get('name') or 'the hiring manager'} ({person.get('headline') or ''}) about the posting "
                f"'{title}' at {company}. Open with 'Hi {first},'. One sentence of proof from the resume with a real number, "
                f"one line on fit, one ask for a 15-minute call. Name the role exactly as '{title}'; never invent a title or "
                f"a seniority level; do not claim more than 2 years of experience. No flattery, no 'I hope this finds you well'.\n\n"
                f"CANDIDATE RESUME:\n{me.get('resume', '')[:3500]}",
                system="You write short, specific recruiter messages for a software engineer. Reply with the message only.",
                max_tokens=220, temperature=0.4, timeout=120)
            if out and isinstance(out, str) and 20 < len(out.split()) <= 95:
                return out.strip()
        except Exception as exc:  # noqa: BLE001
            log.debug("inmail via model failed: %s", exc)
    return (f"Hi {first}, I saw the {title} opening at {company}. I'm a {me.get('role', 'Backend Software Engineer')} with 2 years in "
            f"production on {me.get('stack', 'Java, Kafka, PostgreSQL and AWS')}: I redesigned Kafka consumption on a 400-camera "
            f"analytics platform and took sustained throughput from 30 to 500+ events/sec. I've applied and would value 15 minutes "
            f"to hear what the team needs most. Thanks, {me.get('name', 'Manik')}")


# ----------------------------------------------------------------------------- likes

def pick_posts_to_like(store: dict, liked: dict, want: int, hours: float = 36.0, now: datetime | None = None) -> list[dict]:
    """The freshest hiring posts for your roles that were not liked yet, most-reacted first."""
    now = now or datetime.now(timezone.utc)
    posts = []
    for p in (store.get("posts") or []) if isinstance(store, dict) else []:
        if not isinstance(p, dict) or not p.get("url") or p.get("url") in liked:
            continue
        if p.get("link_kind", "post") != "post" or p.get("open_to_work") or p.get("hiring") is False:
            continue
        when = p.get("posted_at") or p.get("first_seen") or ""
        try:
            at = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            age = (now - at).total_seconds() / 3600
        except (TypeError, ValueError):
            age = float(p.get("hours_old") or 999)
        if age > hours:
            continue
        posts.append((int(p.get("reactions") or 0), -age, p))
    posts.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [p for _, _, p in posts[:want]]


_LIKE_BUTTON = "button[aria-label*='React Like' i], button[aria-label^='Like' i][aria-pressed], button.react-button__trigger"


def like_post(page, url: str) -> str:
    """'liked' | 'already' | 'no-button' | 'error'."""
    from . import human
    if not _goto(page, url, settle=4):
        return "error"
    try:
        human.wander(page)
        btn = page.locator(_LIKE_BUTTON).first
        if not btn.count():
            return "no-button"
        if (btn.get_attribute("aria-pressed") or "").lower() == "true":
            return "already"
        human.click(page, btn)
        page.wait_for_timeout(random.uniform(1200, 2200))
        pressed = (btn.get_attribute("aria-pressed") or "").lower()
        return "liked" if pressed in ("true", "") else "error"
    except Exception as exc:  # noqa: BLE001
        log.warning("like failed at %s: %s", url, str(exc)[:140])
        return "error"


# ----------------------------------------------------------------------------- the daily post draft

# One topic a day, in this order, from the resume. Each: a hook, the facts the post can use, the lesson, the ask.
TOPICS = [
    {"key": "kafka-16x", "hook": "We took a Kafka pipeline from 30 to 500+ events/sec. The fix was not more hardware.",
     "facts": ["400+ cameras, 200+ servers feeding ANPR, face recognition and intrusion events",
               "the bottleneck was one shared topic; event-specific topics plus dead-letter handling fixed it",
               "failed messages now replay from the DLQ instead of blocking the stream"],
     "lesson": "Throughput problems are usually topology problems first.", "ask": "How do you split topics in your event pipelines?"},
    {"key": "timescale", "hook": "Camera frames went from 70 to 300+ per second on the same PostgreSQL box.",
     "facts": ["TimescaleDB hypertables and native compression on the frame tables", "retention policies so the hot set stays small",
               "composite indexes matched to the actual query shapes, latency down 35%"],
     "lesson": "Know your query shapes before you add an index.", "ask": "Postgres or a dedicated time-series store for sensor data?"},
    {"key": "exports-92", "hook": "An analytics export took 12 minutes and crashed with out-of-memory. Now it takes under a minute.",
     "facts": ["100K+ records read as a stream instead of one giant list", "incremental batches with bounded memory",
               "no more OOM failures in production"],
     "lesson": "Streaming reads beat clever caching for big exports.", "ask": "What is your go-to pattern for large exports?"},
    {"key": "milvus", "hook": "Face enrollment and watchlists on Milvus: 75% less vector-index memory, same match accuracy.",
     "facts": ["vector similarity search for enrollment, watchlists and deduplication", "index type and parameters tuned against real match rates",
               "memory matters when the index lives next to video analytics"],
     "lesson": "Measure accuracy and memory together, never one alone.", "ask": "Which vector store are you using in production?"},
    {"key": "webrtc", "hook": "Sub-200 ms live camera playback in the browser. Side project, C++17 and FFmpeg.",
     "facts": ["H.264 decoded and remuxed for live and recorded sources", "transport moved from WebSocket to WebRTC/RTP with libdatachannel",
               "seek, pause and speed over a data channel; CMake, vcpkg, Docker, GitHub Actions, MSI packaging"],
     "lesson": "The transport layer decides your latency floor.", "ask": "Anyone shipped WebRTC for CCTV-style playback?"},
    {"key": "parknest", "hook": "Two people booking the same parking slot at the same second. ParkNest never double-books.",
     "facts": ["optimistic concurrency on bookings", "an idempotent credit ledger so retries never charge twice",
               "normalized PostgreSQL schema, REST APIs, React front end"],
     "lesson": "Idempotency keys are cheaper than refunds.", "ask": "How do you test race conditions in booking flows?"},
    {"key": "libraries", "hook": "New services used to take days to wire up storage and messaging. Now it takes hours.",
     "facts": ["one abstraction over Kafka, local disk, NAS and AWS S3", "adopted by 4+ services",
               "the same code path in dev and production"],
     "lesson": "Write the library after the second copy-paste, not the fifth.", "ask": "When do you extract a shared library?"},
    {"key": "releases", "hook": "Release turnaround down 40% with Docker and GitHub Actions. The changelog writes itself.",
     "facts": ["Docker-based builds, automated changelog from commits", "Grafana and Prometheus dashboards with alerts for every service"],
     "lesson": "Observability is part of the release, not an afterthought.", "ask": "What does your release checklist look like?"},
    {"key": "mentoring", "hook": "Mentoring two junior engineers taught me more about Clean Architecture than any book.",
     "facts": ["async service patterns explained until they could explain them back", "code reviews that cut QA-reported regressions"],
     "lesson": "If you cannot explain the boundary, the boundary is wrong.", "ask": "What is the one thing you wish someone told you in year one?"},
    {"key": "leetcode", "hook": "800+ LeetCode problems. Here is what actually carried over to production work.",
     "facts": ["graphs and trees show up in dependency resolution and permission checks", "two-pointer and sliding window in stream processing",
               "top 5 percentile nationally in Adobe GenSolve"],
     "lesson": "DSA practice pays off when you recognise the shape in real code.", "ask": "Which problem pattern do you see most at work?"},
    {"key": "relocate", "hook": "Backend engineer, 2 years in production, open to relocating. Here is what I bring.",
     "facts": ["Java, Spring Boot, Kafka, PostgreSQL/TimescaleDB, AWS, Docker", "16x throughput and 92% faster exports on a live video analytics platform",
               "valid passport, ready to relocate to Europe, UK, Canada, Singapore, UAE, Australia or Japan"],
     "lesson": "I am looking for a team that ships distributed systems and sponsors visas.", "ask": "If your team is hiring backend engineers abroad, I would love an intro."},
    {"key": "dlq", "hook": "A dead-letter queue is not a trash can. It is a replay buffer.",
     "facts": ["failed events isolated per topic", "replay after the fix, with no data loss", "alerts on DLQ depth in Grafana"],
     "lesson": "Design the replay path before the first failure.", "ask": "How do you handle poison messages?"},
    {"key": "bulk", "hook": "Bulk enrollment of 5,000+ records with live progress in the browser.",
     "facts": ["server-side validation before anything is written", "progress streamed to the UI while the batch runs",
               "government e-challan REST APIs integrated into the ANPR violation pipeline"],
     "lesson": "Users forgive slow. They do not forgive silent.", "ask": "Server-sent events or WebSockets for progress?"},
    {"key": "components", "hook": "10+ React component libraries on NPM, used across 200+ servers. Lessons in API design.",
     "facts": ["one behaviour standard across products", "60+ concurrent users on the deployed apps", "versioning that did not break consumers"],
     "lesson": "A component's props are a public API. Treat them like one.", "ask": "Monorepo or separate packages for shared UI?"},
    {"key": "postgres-tuning", "hook": "35% lower query latency without touching application code.",
     "facts": ["EXPLAIN ANALYZE on the top 20 queries", "composite indexes in column order of the WHERE clauses", "partitioning and compression for the cold data"],
     "lesson": "The database will tell you what it needs if you ask it.", "ask": "What is your favourite Postgres tuning win?"},
    {"key": "clean-arch", "hook": "Clean Architecture in a Spring Boot service: what we kept and what we dropped.",
     "facts": ["domain code with no framework imports", "adapters for Kafka, S3 and Postgres behind interfaces", "SOLID where it paid for itself"],
     "lesson": "Boundaries are for testing first, purity second.", "ask": "How strict are you about layering?"},
    {"key": "dotnet-java", "hook": "Shipping in both Java/Spring and C#/ASP.NET Core. The differences that matter.",
     "facts": ["Hibernate/JPA and EF Core solve the same problems differently", "both run fine in Docker on Linux", "the patterns transfer; the tooling does not"],
     "lesson": "Learn the second stack. It makes the first one clearer.", "ask": "Which stack do you reach for on a new service?"},
    {"key": "observability", "hook": "Every production service here has a Grafana dashboard and an alert. That was not always true.",
     "facts": ["Prometheus metrics per consumer group", "alerts on lag, error rate and DLQ depth", "dashboards reviewed in every incident"],
     "lesson": "If it is not on a dashboard, it is not in production.", "ask": "What is the one metric you always alert on?"},
    {"key": "api-design", "hook": "Integrating government e-challan APIs taught me what a good REST API looks like, by contrast.",
     "facts": ["retries with idempotency on our side", "clear error contracts", "versioned endpoints"],
     "lesson": "Design the error responses first.", "ask": "What is the worst external API you have integrated?"},
    {"key": "s3-nas", "hook": "The same storage code writes to local disk, NAS and S3. Here is how.",
     "facts": ["one interface, three adapters", "config decides the backend per deployment", "tests run against the disk adapter"],
     "lesson": "Abstract storage early. Customers change their minds about where data lives.", "ask": "Do you abstract storage or go all-in on one cloud?"},
    {"key": "interviews", "hook": "Three weeks into a focused job search. What is working on LinkedIn, honestly.",
     "facts": ["applying where I am a top applicant beats applying everywhere", "a specific message to the hiring manager gets replies",
               "posting about real work brings recruiters to the profile"],
     "lesson": "Fewer, better applications.", "ask": "Recruiters: what makes you open a profile?"},
    {"key": "ci", "hook": "GitHub Actions for a C++ project with vcpkg and MSI packaging. It can be done cleanly.",
     "facts": ["cached vcpkg dependencies", "one-command deployment via MSI", "Docker image and Windows installer from the same pipeline"],
     "lesson": "Make the build boring.", "ask": "How do you cache native dependencies in CI?"},
    {"key": "thanks", "hook": "Two years at I2V Systems: the numbers I am proudest of.",
     "facts": ["16x event throughput", "92% faster exports", "75% less vector memory", "40% faster releases"],
     "lesson": "Every one of these started as a complaint from a user.", "ask": "What is the metric you are proudest of this year?"},
]


def topic_for(day_index: int) -> dict:
    return TOPICS[day_index % len(TOPICS)]


def template_post(topic: dict, hashtags: list[str]) -> str:
    lines = [topic["hook"], ""]
    lines += [f"• {f}" for f in topic["facts"]]
    lines += ["", topic["lesson"], "", topic["ask"], "", " ".join(hashtags[:5])]
    return "\n".join(lines)


def draft_post(topic: dict, me: dict, hashtags: list[str]) -> tuple[str, str]:
    """(text, source) - the local model's draft when it is there, else the template."""
    ai = _localai()
    if ai is not None:
        try:
            out = ai.ask(
                "Write a LinkedIn post (120-180 words, plain text, short lines, no emojis, no hashtags in the body) for the engineer "
                f"below. Topic hook: {topic['hook']}\nFacts to use (only these, with their numbers): " + "; ".join(topic["facts"]) +
                f"\nLesson to land: {topic['lesson']}\nEnd with this question: {topic['ask']}\n"
                "First person, concrete, no buzzwords, no 'thrilled to share'. Return the post only.\n\n"
                f"RESUME FOR CONTEXT:\n{me.get('resume', '')[:3000]}",
                system="You write clear, specific LinkedIn posts for a backend engineer. Reply with the post only.",
                max_tokens=420, temperature=0.6, timeout=150)
            if out and isinstance(out, str) and 60 <= len(out.split()) <= 260:
                return out.strip() + "\n\n" + " ".join(hashtags[:5]), "local model"
        except Exception as exc:  # noqa: BLE001
            log.debug("draft via model failed: %s", exc)
    return template_post(topic, hashtags), "template"


def write_draft(cfg: dict, state: dict, me: dict, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    idx = int(state.get("draft_index") or 0)
    topic = topic_for(idx)
    text, source = draft_post(topic, me, list(cfg.get("hashtags") or DEFAULTS["hashtags"]))
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / f"{today_key(now)}.md"
    body = (f"# Post draft for {today_key(now)}  (topic: {topic['key']}, written by the {source})\n\n"
            f"Copy the text below into a LinkedIn post. Best times: 8:30-10:00 or 17:30-19:00 IST, Tuesday to Thursday.\n"
            f"Reply to every comment within the first hour; that is what the feed rewards.\n\n---\n\n{text}\n")
    path.write_text(body, encoding="utf-8")
    (DRAFTS_DIR / "TODAY.md").write_text(body, encoding="utf-8")
    state["draft_index"] = idx + 1
    d = day(state, now)
    d["drafted"] += 1
    d["draft_path"] = str(path)
    d["draft_topic"] = topic["key"]
    log.info("post draft written (%s, topic %s): %s", source, topic["key"], path)
    return path


# ----------------------------------------------------------------------------- about you

def about_me() -> dict:
    """Name, role, stack and resume text for the drafts. From resume/*.txt, else data/profile.txt."""
    me = {"name": "Manik", "role": "Backend Software Engineer", "stack": "Java, Kafka, PostgreSQL, AWS", "resume": ""}
    # the resume stored for this computer first (site\set_resume.bat), read through job-hunt's extractor
    try:
        scripts = ROOT.parent / "job-hunt" / "scripts"
        if scripts.is_dir() and str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from jobbot.resume import device_resume_path, extract_text  # type: ignore
        dev = device_resume_path()
        if dev:
            me["resume"] = extract_text(dev)
    except Exception as exc:  # noqa: BLE001 - then the project's own resume text
        log.debug("device resume not read: %s", exc)
    for p in ([] if me["resume"] else sorted((ROOT / "resume").glob("*.txt"))):
        try:
            me["resume"] = p.read_text(encoding="utf-8", errors="ignore")
            break
        except OSError:
            continue
    if not me["resume"]:
        try:
            me["resume"] = (ROOT / "data" / "profile.txt").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    lines = [ln.strip() for ln in me["resume"].splitlines() if ln.strip()]
    if lines:
        me["name"] = lines[0].title().split(" ")[0] if lines[0].isupper() else lines[0].split(" ")[0]
        if len(lines) > 1 and "|" in lines[1]:
            role, _, stack = lines[1].partition("|")
            me["role"], me["stack"] = role.strip(), stack.strip()
    return me


# ----------------------------------------------------------------------------- the report

ABROAD_CHECKLIST = """\
## Abroad: what the automation cannot do for you (do once, 20 minutes)

1. **Open to Work** (profile > Open to): add job titles Backend Engineer / Software Engineer / Java Developer, and under
   *Locations* add every country in `abroad_countries` plus "Remote". Keep it visible to **recruiters only** unless you want the banner.
2. **Headline**: "Backend Software Engineer | Java, Kafka, PostgreSQL, AWS | Open to relocation (EU/UK/CA/SG/AE)". Recruiter search
   matches the headline first; the words "relocation" and "visa sponsorship" are what abroad recruiters filter on.
3. **Location field**: keep Gurugram, but write in About: "Ready to relocate; valid passport; no visa needed for the UAE".
4. **Premium Open-to-Work + Top Applicant** work abroad too: the pass searches each country daily and ranks visa-sponsoring postings first.
5. **Where it is realistic for 2 years of Java/Kafka**: Germany (Opportunity Card or a Blue Card once hired), Netherlands (Highly
   Skilled Migrant via a recognised sponsor), Ireland (Critical Skills permit, employer applies), UAE and Singapore (employer-driven,
   fastest), Canada (remote-first firms, then PR routes), UK (Skilled Worker needs a licensed sponsor). Japan hires backend engineers
   with English only at product companies; the list above is searched daily.
6. **Weekly**: send 2 of your 5 InMails to hiring managers named in this report, abroad first. Spend the other 3 on India roles that
   list you as a top applicant.
"""


def _md_table(rows: list[list[str]], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out)


def write_report(cfg: dict, state: dict, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    d = day(state, now)
    key = today_key(now)
    reach = state.get("reach") or []
    left = days_left(cfg, now.date())
    lines = [f"# LinkedIn Premium, {key}  ({left} day(s) of Premium left, until {cfg.get('until')})", ""]
    lines.append(f"Passes today: {d['passes']}  |  applied: {d['applied']}  |  liked: {d['liked']}  |  new viewers: {d['viewers_new']}  "
                 f"|  leads: {len(d['leads'])}  |  pages opened: {d['opened']}  |  connections sent: {d['connected']}")
    lines.append("")
    if reach:
        lines.append("## Reach")
        rows = []
        for r in reach[-7:]:
            rows.append([r.get("date", ""), r.get("profile_views", "-"), r.get("post_impressions", "-"), r.get("search_appearances", "-")])
        lines.append(_md_table(rows, ["day", "profile views (90d)", "post impressions (7d)", "search appearances (7d)"]))
        lines.append("")
    if d.get("draft_path"):
        lines.append(f"## Today's post to publish yourself\n\n`{d['draft_path']}`  (topic: {d.get('draft_topic')}). Also in drafts/TODAY.md.\n")
    if d["applied_jobs"]:
        lines.append("## Applied this day (Easy Apply, by this module)")
        lines.append(_md_table([[j.get("score", ""), j.get("title", ""), j.get("company", ""), j.get("location", ""),
                                 ", ".join(j.get("why") or []), f"[open]({j.get('url')})", j.get("status", "")] for j in d["applied_jobs"]],
                               ["score", "title", "company", "location", "why", "link", "status"]))
        lines.append("")
    if d["offsite"]:
        lines.append("## Apply yourself (Apply leads off LinkedIn), best first")
        lines.append(_md_table([[j.get("score", ""), j.get("title", ""), j.get("company", ""), j.get("location", ""),
                                 ", ".join(j.get("why") or []), f"[open]({j.get('url')})"] for j in d["offsite"][:25]],
                               ["score", "title", "company", "location", "why", "link"]))
        lines.append("")
    if d["inmails"]:
        lines.append("## InMail drafts (5 credits a month: send the best ones yourself)")
        for m in d["inmails"][:6]:
            lines.append(f"**{m['to']}** ({m.get('headline', '')}) about *{m['job']}* at {m['company']}: [person]({m['person_url']}) · [job]({m['job_url']})")
            lines.append("")
            lines.append("> " + m["text"].replace("\n", "\n> "))
            lines.append("")
    if d["leads"]:
        lines.append("## Recruiters and hiring people who viewed your profile (connect or message them today)")
        for v in d["leads"][:20]:
            lines.append(f"- **{v['name']}**, {v.get('headline', '')} · [profile]({v['url']}) · {v.get('status', 'note drafted')}")
            lines.append(f"  > {v.get('note', '')}")
        lines.append("")
    if d["liked_posts"]:
        lines.append("## Liked today")
        lines += [f"- {p.get('author', '')}: [{(p.get('text') or '')[:70]}...]({p.get('url')}) ({p.get('status')})" for p in d["liked_posts"]]
        lines.append("")
    if d["skipped"]:
        lines.append("<details><summary>Looked at and skipped</summary>\n")
        lines += [f"- {s}" for s in d["skipped"][:40]]
        lines.append("\n</details>\n")
    if d["errors"]:
        lines.append("## Problems this day")
        lines += [f"- {e}" for e in d["errors"][:20]]
        lines.append("")
    lines.append(ABROAD_CHECKLIST)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"{key}.md"
    text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")
    (DIR / "LATEST.md").write_text(text, encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- the phone: report, draft, tasks, posting

PHONE_PATH = "data/premium/latest.json"
# The scheduled tasks the phone may show and start / stop (scripts\schedule_*.ps1 register them).
TASKS = ["LinkedInPremium", "SocialPostsWatch", "LinkedInPostsWatch", "JobHuntApply", "PhoneApplyQueue", "NaukriProfileRefresh"]
TASK_PREFIXES = ["NaukriJobAgent"]


def tasks_status() -> list[dict]:
    """[{name, state, enabled, last_run, last_result, next_run}] from Task Scheduler (Windows only)."""
    if os.name != "nt":
        return []
    import subprocess
    names = ", ".join(f"'{n}'" for n in TASKS + [f"{p}*" for p in TASK_PREFIXES])
    script = (f"$t = Get-ScheduledTask -TaskName {names} -ErrorAction SilentlyContinue | ForEach-Object {{ $i = $_ | Get-ScheduledTaskInfo; "
              "[pscustomobject]@{ name = $_.TaskName; state = [string]$_.State; enabled = $_.Settings.Enabled; "
              "last_run = $(if ($i.LastRunTime) { $i.LastRunTime.ToString('s') } else { '' }); last_result = $i.LastTaskResult; "
              "next_run = $(if ($i.NextRunTime) { $i.NextRunTime.ToString('s') } else { '' }); description = $_.Description } }; "
              "if ($t -eq $null) { '[]' } else { ConvertTo-Json @($t) -Compress }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(out.stdout.strip() or "[]")
        rows = data if isinstance(data, list) else [data]
    except Exception as exc:  # noqa: BLE001
        log.debug("tasks not read: %s", exc)
        return []
    order = {n: i for i, n in enumerate(TASKS)}
    rows.sort(key=lambda r: (order.get(r.get("name"), 99), r.get("name") or ""))
    return [{k: r.get(k) for k in ("name", "state", "enabled", "last_run", "last_result", "next_run", "description")} for r in rows]


def control_task(name: str, do: str) -> str:
    """start = enable + start now; stop = stop + disable (so the 30-min check does not restart it);
    run = start now (keep enabled); enable / disable. Returns a one-line result."""
    if os.name != "nt":
        return "not Windows"
    import subprocess
    known = name in TASKS or any(name.startswith(p) for p in TASK_PREFIXES)
    if not known or not re.match(r"^[\w\-]+$", name or ""):
        return f"unknown task {name!r}"
    cmds = {"start": f"Enable-ScheduledTask -TaskName '{name}' | Out-Null; Start-ScheduledTask -TaskName '{name}'",
            "run": f"Start-ScheduledTask -TaskName '{name}'",
            "stop": f"Stop-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; Disable-ScheduledTask -TaskName '{name}' | Out-Null",
            "enable": f"Enable-ScheduledTask -TaskName '{name}' | Out-Null",
            "disable": f"Disable-ScheduledTask -TaskName '{name}' | Out-Null"}
    if do not in cmds:
        return f"unknown action {do!r}"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmds[do] + "; 'ok'"],
                             capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = (out.stderr or "").strip()
        return f"{do} {name}: " + ("ok" if "ok" in (out.stdout or "") and not err else (err[:200] or f"exit {out.returncode}"))
    except Exception as exc:  # noqa: BLE001
        return f"{do} {name}: {str(exc)[:200]}"


def phone_payload(cfg: dict, state: dict, now: datetime | None = None) -> dict:
    """What the phone's Premium tab shows: the day's numbers, the draft to post, the report, the PC's tasks."""
    now = now or datetime.now()
    key = today_key(now)
    d = day(state, now)
    draft = None
    for p in (DRAFTS_DIR / f"{key}.md", DRAFTS_DIR / "TODAY.md"):
        if p.exists():
            text = p.read_text(encoding="utf-8")
            body = text.split("\n---\n", 1)[1].strip() if "\n---\n" in text else text
            draft = {"date": key, "topic": d.get("draft_topic") or "", "text": body, "posted": d.get("posted") or None}
            break
    report = ""
    rp = DAILY_DIR / f"{key}.md"
    if rp.exists():
        report = rp.read_text(encoding="utf-8")
    return {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "date": key, "until": str(cfg.get("until")),
            "days_left": days_left(cfg, now.date()), "host": os.environ.get("COMPUTERNAME", ""),
            "day": {k: d.get(k) for k in ("passes", "applied", "liked", "connected", "drafted", "viewers_new", "opened", "posted")},
            "counts": {"leads": len(d["leads"]), "inmails": len(d["inmails"]), "offsite": len(d["offsite"]), "errors": len(d["errors"])},
            "reach": (state.get("reach") or [])[-14:], "draft": draft, "report_md": report[:120000],
            "tasks": tasks_status(), "connect_per_day": int(cfg.get("connect_per_day", 0)), "apply_per_day": int(cfg.get("apply_per_day", 8))}


def publish_phone(cfg: dict, state: dict, now: datetime | None = None) -> bool:
    """data/premium/latest.json on gh-pages, through the GitHub API (no clone, like the posts watchers)."""
    tools = ROOT.parent / "site" / "tools"
    if not (tools / "pages_git.py").exists():
        return False
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import pages_git  # type: ignore
        repo_url = None
        try:
            from phone_publish import load_config as _phone_cfg  # type: ignore
            repo_url = (_phone_cfg() or {}).get("repo_url")
        except (SystemExit, Exception):  # noqa: BLE001
            repo_url = None
        payload = phone_payload(cfg, state, now)
        pages_git.put_file(repo_url or pages_git.default_repo_url(), PHONE_PATH,
                           json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                           "premium: %s, %d day(s) left, applied %s" % (payload["date"], payload["days_left"], payload["day"].get("applied")))
        return True
    except (SystemExit, Exception) as exc:  # noqa: BLE001
        log.warning("phone publish failed: %s", str(exc)[:300])
        return False


_START_POST = ("button:has-text('Start a post'), button[aria-label*='Start a post' i], "
               "div[role='button']:has-text('Start a post'), button:has-text('Create a post')")
_POST_BOX = "div[role='textbox'][contenteditable='true'], div.ql-editor[contenteditable='true']"
_POST_BUTTON = "button.share-actions__primary-action, button:has-text('Post')[class*='share'], div[role='dialog'] button:has-text('Post')"


def _post_button(page):
    """The composer's Post button. The Oct 2026 composer has hashed class names and no dialog role:
    the button is the one visible <button> whose whole text is 'Post' (the feed's own buttons say
    'Repost', 'Hide post by ...')."""
    old = page.locator(_POST_BUTTON).first
    try:
        if old.count() and old.is_visible(timeout=1000):
            return old
    except Exception:  # noqa: BLE001
        pass
    cands = page.locator("button").filter(has_text=re.compile(r"^\s*Post\s*$"))
    try:
        for i in range(cands.count()):
            b = cands.nth(i)
            if b.is_visible(timeout=800):
                return b
    except Exception:  # noqa: BLE001
        pass
    return None


def _composer_open(page) -> bool:
    try:
        return page.locator(_POST_BOX).first.is_visible(timeout=1500)
    except Exception:  # noqa: BLE001
        return False


def post_to_linkedin(page, text: str) -> tuple[str, str]:
    """Publish `text` as a LinkedIn post from the feed. Returns (status, note): posted | error."""
    from . import human
    if not _goto(page, "https://www.linkedin.com/feed/", settle=5):
        return "error", "feed did not open"
    try:
        human.wander(page)
        start = page.locator(_START_POST).first
        if not start.count():
            return "error", "no 'Start a post' control on the feed"
        human.click(page, start)
        page.wait_for_timeout(random.uniform(2500, 4000))
        box = page.locator(_POST_BOX).first
        if not box.count():
            return "error", "post editor did not open"
        human.click(page, box)
        page.wait_for_timeout(random.uniform(500, 900))
        # typed line by line: the editor turns Enter into paragraphs, insert_text keeps the line breaks
        page.keyboard.type(text[:40], delay=random.uniform(40, 90))
        page.keyboard.insert_text(text[40:])
        page.wait_for_timeout(random.uniform(1500, 2500))
        typed = (box.inner_text(timeout=3000) or "").strip()
        if len(typed) < min(60, len(text) // 2):
            return "error", "the editor did not take the text"
        btn = _post_button(page)
        if btn is None:
            return "error", "no Post button"
        if not btn.is_enabled(timeout=2000):
            return "error", "the Post button stayed disabled"
        human.click(page, btn)
        page.wait_for_timeout(random.uniform(4000, 6000))
        body = _body(page, 3000)
        if re.search(r"post successful|your post was published|post published", body, re.I):
            return "posted", "LinkedIn confirmed the post"
        if _composer_open(page):
            return "error", "the composer is still open (LinkedIn did not accept the post)"
        return "posted", "composer closed after Post"
    except Exception as exc:  # noqa: BLE001
        return "error", str(exc)[:200]


def post_draft(text: str, headless: bool = True, cfg: dict | None = None) -> tuple[str, str]:
    """Open the saved LinkedIn session, publish the text, remember it in the day's state, republish the phone file."""
    from playwright.sync_api import sync_playwright
    from . import linkedin as linkedin_mod
    cfg = cfg or load_config()
    state = load_state()
    d = day(state)
    with sync_playwright() as p:
        browser, _ctx, page = linkedin_mod.open_session(p, headless=headless)
        try:
            status, note = post_to_linkedin(page, text)
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
    d["posted"] = {"at": datetime.now().isoformat(timespec="seconds"), "status": status, "note": note, "chars": len(text)}
    if status == "posted":
        d["errors"] = [e for e in d["errors"] if not e.startswith("post:")]
    else:
        d["errors"].append(f"post: {note}")
    save_state(state)
    write_report(cfg, state)
    publish_phone(cfg, state)
    log.info("post from the phone: %s (%s)", status, note)
    return status, note


# ----------------------------------------------------------------------------- a pass

def run_once(cfg: dict, headless: bool = True, dry_run: bool = False, state_path: Path = STATE_PATH) -> dict:
    from playwright.sync_api import sync_playwright

    from . import linkedin as linkedin_mod
    from . import linkedin_apply, linkedin_limit, applications, questions
    from . import answers as answers_mod
    from . import config as config_mod

    state = load_state(state_path)
    now = datetime.now()
    d = day(state, now)
    d["passes"] += 1
    me = about_me()
    t0 = time.time()
    log.info("pass %d on %s: %d day(s) of Premium left%s", d["passes"], today_key(now), days_left(cfg, now.date()),
             " (dry run)" if dry_run else "")

    # the daily draft needs no browser, so it never waits on one
    if d["drafted"] < int(cfg.get("draft_per_day", 1)):
        try:
            write_draft(cfg, state, me, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("draft failed: %s", exc)
            d["errors"].append(f"draft: {str(exc)[:120]}")
        save_state(state, state_path)

    profile = config_mod.load_profile()
    config = config_mod.load(profile=profile)
    facts = answers_mod.build_facts(profile, config)
    facts["_bank"] = questions.load_bank()
    phone = str(facts.get("stated_phone") or "").strip() or None
    daily_cap = int(config.get("linkedin_max_applies_per_day") or 25)
    exclude_companies = [str(c).strip().lower() for c in (config.get("exclude_companies") or []) if str(c).strip()]

    with sync_playwright() as p:
        browser, ctx, page = linkedin_mod.open_session(p, headless=headless)
        try:
            # 1. reach
            try:
                r = read_reach(page)
                if r:
                    r["date"] = today_key(now)
                    reach = [x for x in state.get("reach") or [] if x.get("date") != r["date"]]
                    reach.append(r)
                    state["reach"] = reach[-60:]
                    log.info("reach: %s", ", ".join(f"{k} {v}" for k, v in r.items() if k != "date"))
                else:
                    log.info("reach: nothing read from the profile page")
            except Exception as exc:  # noqa: BLE001
                log.exception("reach failed: %s", exc)
                d["errors"].append(f"reach: {str(exc)[:120]}")
            _pause()

            # 2. viewers
            try:
                vs = read_viewers(page)
                known = state.setdefault("viewers", {})
                new_leads = []
                for v in vs["viewers"]:
                    if v["url"] in known:
                        continue
                    known[v["url"]] = {"name": v["name"], "headline": v["headline"], "first_seen": now.isoformat(timespec="seconds")}
                    d["viewers_new"] += 1
                    if is_recruiter(v["headline"]):
                        lead = dict(v, note=connection_note(v, me), status="note drafted", seen=today_key(now))
                        d["leads"].append(lead)
                        new_leads.append(lead)
                log.info("viewers: %d listed, %d private, %d new, %d new recruiter/hiring lead(s)",
                         len(vs["viewers"]), vs["private"], d["viewers_new"], len(new_leads))
                for lead in new_leads:
                    log.info("  lead: %s - %s  %s", lead["name"], lead["headline"][:80], lead["url"])
                want = int(cfg.get("connect_per_day", 0)) - int(d["connected"])
                for lead in new_leads:
                    if want <= 0 or dry_run:
                        break
                    _pause()
                    status = connect_with(page, lead, lead["note"])
                    lead["status"] = f"connection {status}"
                    log.info("  connect %s: %s", lead["name"], status)
                    if status == "sent":
                        d["connected"] += 1
                        want -= 1
            except linkedin_mod.NotLoggedIn:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("viewers failed: %s", exc)
                d["errors"].append(f"viewers: {str(exc)[:120]}")
            save_state(state, state_path)
            _pause()

            # 3. jobs
            try:
                seen_jobs = state.setdefault("jobs", {})
                cards: dict[str, dict] = {}
                for label, url in job_urls_for_pass(cfg, state, linkedin_mod):
                    got = cards_at(page, url, linkedin_mod)
                    fresh = 0
                    for c in got:
                        jid = str(c.get("job_id"))
                        if not jid or jid in cards:
                            continue
                        c["source"] = label
                        if jid in seen_jobs and seen_jobs[jid].get("status") not in (None, "", "candidate"):
                            continue
                        if any(x in (c.get("company") or "").lower() for x in exclude_companies):
                            continue
                        if cfg.get("exclude_senior", True) and SENIOR_RX.search(c.get("title") or ""):
                            continue
                        cards[jid] = c
                        fresh += 1
                    log.info("jobs %-28s %2d card(s), %2d new", label, len(got), fresh)
                    _pause(2.5, 5.0)
                # Premium's collection first, then Easy Apply, then the rest; open at most open_per_pass pages
                order = sorted(cards.values(), key=lambda c: (c.get("source") != "top-applicant", not c.get("easy_apply"), c.get("promoted", False)))
                budget = apply_budget(cfg, d, daily_cap, today_linkedin_applied())
                paused = linkedin_limit.active()
                if paused:
                    log.info("Easy Apply: %s", linkedin_limit.label())
                log.info("jobs: %d candidate(s); opening up to %d; Easy Apply budget this pass %d (cap %d/day shared, %d/day this module)",
                         len(order), int(cfg.get("open_per_pass", 14)), budget, daily_cap, int(cfg.get("apply_per_day", 8)))
                ranked: list[tuple[int, list[str], dict, dict]] = []
                for c in order[:int(cfg.get("open_per_pass", 14))]:
                    info = inspect_job(page, c)
                    d["opened"] += 1
                    score, why = rank(c, info, cfg)
                    ranked.append((score, why, c, info))
                    seen_jobs[str(c["job_id"])] = {"title": c.get("title"), "company": c.get("company"), "location": c.get("location"),
                                                   "score": score, "why": why, "seen": today_key(now), "status": "candidate",
                                                   "top_applicant": info.get("top_applicant", False), "source": c.get("source")}
                    log.info("  %4d  %-44s %-24s %-22s %s", score, (c.get("title") or "")[:44], (c.get("company") or "")[:24],
                             (c.get("location") or "")[:22], ", ".join(why))
                    _pause(2.0, 4.5)
                ranked.sort(key=lambda t: t[0], reverse=True)
                for score, why, c, info in ranked:
                    rec = seen_jobs[str(c["job_id"])]
                    entry = {"score": score, "why": why, "title": c.get("title"), "company": c.get("company"), "location": c.get("location"),
                             "url": c.get("url"), "top_applicant": info.get("top_applicant", False)}
                    if score <= 0:
                        rec["status"] = "skipped"
                        d["skipped"].append(f"{c.get('title')} at {c.get('company')} ({c.get('location')}): {', '.join(why)}")
                        continue
                    # InMail drafts for the best postings with a named hiring team
                    if info.get("hiring_team") and len(d["inmails"]) < 6 and not any(m["job_url"] == c["url"] for m in d["inmails"]):
                        person = info["hiring_team"][0]
                        d["inmails"].append({"to": person.get("name") or "hiring team", "headline": person.get("headline", ""),
                                             "person_url": person.get("url"), "job": c.get("title"), "company": c.get("company"),
                                             "job_url": c.get("url"), "text": inmail_draft(c, person, me)})
                    if not info.get("easy_apply"):
                        rec["status"] = "offsite"
                        if not any(o["url"] == c["url"] for o in d["offsite"]):
                            d["offsite"].append(entry)
                        continue
                    if already_tried(c["job_id"]):
                        rec["status"] = "tried-before"
                        continue
                    if dry_run:
                        rec["status"] = "candidate"
                        d["skipped"].append(f"dry run, would apply: {c.get('title')} at {c.get('company')} ({score})")
                        continue
                    if budget <= 0 or paused:
                        rec["status"] = "candidate"        # tomorrow's budget
                        continue
                    capture: dict = {}
                    job = SimpleNamespace(job_id=c["job_id"], title=c.get("title"), company=c.get("company"), url=c.get("url"),
                                          location=c.get("location"), score=score, description=info.get("text", ""))
                    status, note = linkedin_apply.apply_to(page, c, facts, dry_run=False, phone=phone, capture=capture)
                    log.info("  apply %-44s %-24s -> %s: %s", (c.get("title") or "")[:44], (c.get("company") or "")[:24], status, note[:100])
                    applications.record("linkedin", job, status, note, capture, project="premium")
                    entry["status"] = status
                    if status == "applied":
                        d["applied"] += 1
                        budget -= 1
                        rec["status"] = "applied"
                        d["applied_jobs"].append(entry)
                    elif status == "limit-reached":
                        linkedin_limit.hit()
                        paused = True
                        rec["status"] = "candidate"
                    elif status == "questionnaire":
                        rec["status"] = "questionnaire"
                        if capture.get("question"):
                            try:
                                questions.record(capture["question"], capture.get("options") or [], job, "linkedin")
                            except Exception as exc:  # noqa: BLE001
                                log.debug("question not queued: %s", exc)
                        d["applied_jobs"].append(entry)
                    elif status == "offsite":
                        rec["status"] = "offsite"
                        d["offsite"].append(entry)
                    else:
                        rec["status"] = status
                        d["applied_jobs"].append(entry)
                    save_state(state, state_path)
                    _pause(6.0, 14.0)
            except linkedin_mod.NotLoggedIn:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("jobs failed: %s", exc)
                d["errors"].append(f"jobs: {str(exc)[:120]}")
            save_state(state, state_path)

            # 5. likes
            try:
                want = int(cfg.get("likes_per_day", 2)) - int(d["liked"])
                if want > 0:
                    liked = state.setdefault("liked", {})
                    try:
                        store = json.loads(POSTS_STORE.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        store = {}
                    picks = pick_posts_to_like(store, liked, want + 2)
                    if not picks:
                        log.info("likes: no fresh hiring post in %s; the feed is used instead", POSTS_STORE.name)
                        picks = [{"url": "https://www.linkedin.com/feed/", "author": "feed", "text": "first post in the feed"}]
                    for post in picks:
                        if want <= 0:
                            break
                        if dry_run:
                            d["skipped"].append(f"dry run, would like: {post.get('url')}")
                            want -= 1
                            continue
                        _pause()
                        status = like_post(page, post["url"])
                        liked[post["url"]] = today_key(now)
                        d["liked_posts"].append({"url": post["url"], "author": post.get("author", ""), "text": post.get("text", ""), "status": status})
                        log.info("like %s: %s", post["url"], status)
                        if status == "liked":
                            d["liked"] += 1
                            want -= 1
            except linkedin_mod.NotLoggedIn:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("likes failed: %s", exc)
                d["errors"].append(f"likes: {str(exc)[:120]}")
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass

    state["updated"] = now.isoformat(timespec="seconds")
    save_state(state, state_path)
    path = write_report(cfg, state, now)
    if state_path == STATE_PATH:
        publish_phone(cfg, state, now)
    log.info("pass done in %.0fs: applied %d, liked %d, leads %d, inmail drafts %d, offsite %d, opened %d. Report: %s",
             time.time() - t0, d["applied"], d["liked"], len(d["leads"]), len(d["inmails"]), len(d["offsite"]), d["opened"], path)
    return d


def loop(cfg: dict, headless: bool = True, dry_run: bool = False) -> int:
    from . import linkedin as linkedin_mod
    every = int(cfg.get("every_minutes", 240))
    log.info("LinkedIn Premium runner: a pass every %d min until %s (%d day(s) left), %s",
             every, cfg.get("until"), days_left(cfg), "headless" if headless else "visible browser")
    while True:
        if premium_over(cfg):
            log.info("Premium period is over (until %s). Stopping; remove the task with scripts\\schedule_linkedin_premium.ps1 -Remove",
                     cfg.get("until"))
            return 0
        started = time.time()
        wait = every * 60
        try:
            run_once(cfg, headless=headless, dry_run=dry_run)
        except linkedin_mod.NotLoggedIn as exc:
            log.error("%s", exc)
            wait = 60 * 60
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001
            log.exception("pass failed: %s", exc)
        sleep_for = max(300, wait - (time.time() - started) + random.uniform(-600, 600))
        log.info("next pass in %.0f min", sleep_for / 60)
        time.sleep(sleep_for)


def _setup_logging(verbose: bool) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", handlers=handlers)
    for noisy in ("naukri.jobs.linkedin", "naukri.jobs.linkedin_apply", "urllib3", "jobbot.localai"):
        logging.getLogger(noisy).setLevel(logging.INFO if verbose else logging.WARNING)


def _guard_children() -> None:
    guard = ROOT / "scripts" / "jobguard.py"
    if os.name != "nt" or not guard.exists():
        return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("jobguard", str(guard))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)   # type: ignore[union-attr]
        mod.kill_tree_on_exit()
    except Exception as exc:  # noqa: BLE001
        log.debug("job object not set up: %s", exc)


def _keep_awake() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:  # noqa: BLE001
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="one pass now, then the report")
    mode.add_argument("--loop", action="store_true", help="a pass every `every_minutes` until `until`")
    mode.add_argument("--draft", action="store_true", help="only write today's post draft (no browser)")
    mode.add_argument("--report", action="store_true", help="only rebuild today's report from the saved state (and republish it to the phone)")
    mode.add_argument("--post-file", dest="post_file", metavar="FILE", help="publish this text file as a LinkedIn post now (what the phone's Post button does through the PC)")
    ap.add_argument("--show", action="store_true", help="visible browser (default: headless)")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run", help="read and rank everything; apply to nothing, like nothing")
    ap.add_argument("--config", default=str(CONFIG_PATH), help=f"settings file (default {CONFIG_PATH})")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    _setup_logging(args.verbose)
    cfg = load_config(Path(args.config))
    if args.show:
        os.environ["NAUKRI_SHOW"] = "1"
        os.environ.pop("NAUKRI_BACKGROUND", None)
    else:
        os.environ["NAUKRI_BACKGROUND"] = "1"
    _guard_children()
    _keep_awake()

    if args.draft:
        state = load_state()
        path = write_draft(cfg, state, about_me())
        save_state(state)
        write_report(cfg, state)
        publish_phone(cfg, state)
        print(f"\n  {path}\n")
        return 0
    if args.report:
        state = load_state()
        path = write_report(cfg, state)
        print(f"\n  {path}  (phone: {'published' if publish_phone(cfg, state) else 'not published'})\n")
        return 0
    if args.post_file:
        text = Path(args.post_file).read_text(encoding="utf-8").strip()
        status, note = post_draft(text, headless=not args.show, cfg=cfg)
        print(f"\n  {status}: {note}\n")
        return 0 if status == "posted" else 1
    if premium_over(cfg):
        log.info("Premium period is over (until %s); nothing to do", cfg.get("until"))
        return 0
    if args.loop:
        return loop(cfg, headless=not args.show, dry_run=args.dry_run)
    from . import linkedin as linkedin_mod
    try:
        d = run_once(cfg, headless=not args.show, dry_run=args.dry_run)
    except linkedin_mod.NotLoggedIn as exc:
        print(f"\n  {exc}\n")
        return 2
    print(f"\n  applied {d['applied']}, liked {d['liked']}, leads {len(d['leads'])}, InMail drafts {len(d['inmails'])}, "
          f"offsite to apply yourself {len(d['offsite'])}. Report: {DIR / 'LATEST.md'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
