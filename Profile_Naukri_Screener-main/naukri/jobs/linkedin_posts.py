"""Hiring posts on LinkedIn - the "we are hiring" posts people write, not the job listings.

    python -m naukri.jobs.linkedin_posts --once              one pass over the queries, then publish
    python -m naukri.jobs.linkedin_posts --loop              the same every 30 min, for as long as the PC is on
    python -m naukri.jobs.linkedin_posts --once --show       with a visible browser (default: headless)
    python -m naukri.jobs.linkedin_posts --once --debug      also save each result page's HTML under data/posts/

What one pass does:
  1. opens LinkedIn on the saved session (data/linkedin_state.json - `python main.py
     --linkedin-login` once), headless, the same way the job search does (naukri/jobs/linkedin.py)
  2. searches POSTS (LinkedIn's content search), newest first, posted in the last 24 h, for a
     handful of the queries in QUERIES ("hiring software engineer", "hiring SDE", "hiring
     freshers software", "hiring 2025 batch"...), rotating through the list pass by pass
  3. reads every post card: who posted and their headline, when (exact - LinkedIn's activity id
     carries the post's timestamp), the text, reactions and comments, the links and emails in it
  4. keeps the posts that ARE a hiring post (not "I am open to work") for a software role that
     fits 0-2 years - freshers, entry level, "0-2 yrs", a 2024-2026 batch, junior - or that says
     nothing about seniority at all
  5. merges them into data/posts/linkedin_posts.json (one entry per post, a week kept locally)
     and publishes the last WINDOW_HOURS (12) to the phone site as data/posts/linkedin_posts.json,
     through the GitHub API - no clone, so it never collides with the queue run's pushes

Pacing: one result page per query, a human pause between pages, eight queries a pass and a pass
every 30 minutes - about 16 page loads an hour. This module only reads; nothing is liked,
commented on, followed or messaged. Output: logs/linkedin_posts.log.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("naukri.jobs.linkedin_posts")

ROOT = Path(__file__).resolve().parent.parent.parent
STORE_PATH = ROOT / "data" / "posts" / "linkedin_posts.json"
DEBUG_DIR = ROOT / "data" / "posts"
LOG_PATH = ROOT / "logs" / "linkedin_posts.log"
PUBLISH_PATH = "data/posts/linkedin_posts.json"

WINDOW_HOURS = 12          # what the phone shows: posts from the last 12 hours (fixed, as asked)
KEEP_HOURS = 7 * 24        # what the local store remembers, so a post seen again is not a new one
EVERY_MINUTES = 30
PER_PASS = 8               # queries per pass; the list is rotated so every query runs every second pass
MAX_PUBLISHED = 400

SEARCH_URL = "https://www.linkedin.com/search/results/content/"

# The searches. "hiring" + a role, in the words people use in these posts. Edit freely; a line
# in data/posts/queries.txt (one query per line) replaces this list without a code change.
QUERIES = [
    "hiring software engineer",
    "hiring SDE",
    "hiring SWE",
    "hiring software developer",
    "hiring freshers software engineer",
    "hiring 2025 batch software",
    "hiring 2026 batch software engineer",
    "hiring 2024 batch developer",
    "hiring entry level software engineer",
    "hiring junior software engineer",
    "hiring backend developer freshers",
    "hiring frontend developer freshers",
    "hiring full stack developer 0-2 years",
    "hiring java developer freshers",
    "hiring python developer freshers",
    "we are hiring software engineer immediate joiners",
    "hiring new grad software engineer",
    "hiring graduate engineer trainee software",
]

# ----------------------------------------------------------------------------- reading a post

HIRING_RX = re.compile(
    r"\b(we(?:'|’)?re hiring|we are hiring|hiring\b|#hiring|job opening|job openings|openings? for|opening for|"
    r"vacanc(?:y|ies)|urgent(?:ly)? hiring|immediate joiners?|walk[- ]?in|now hiring|"
    r"looking for (?:a |an |passionate |talented |skilled |experienced |motivated |young )?(?:[a-z.+#\-]+ ){0,4}"
    r"(?:engineers?|developers?|sde|swe|programmers?|interns?|freshers?|graduates?|trainees?)|"
    r"apply (?:now|here|at|via|through|by|today|link)|send (?:your |me your |us your |across your )?(?:cv|resume|profile)s?|"
    r"share (?:your |me your |us your )?(?:cv|resume|profile)s?|drop (?:your |me your )?(?:cv|resume|profile)s?|"
    r"dm (?:me|us)\b|refer(?:ral)?s?\b|job alert|job post|recruit(?:ing|ment)\b|open (?:role|position)s?|"
    r"positions? (?:open|available)|join (?:our|us|the) team|career opportunit(?:y|ies)|interested candidates|"
    r"mail (?:your |me your )?(?:cv|resume)|email (?:your |me your )?(?:cv|resume)|applications? (?:are )?open|interview drive|"
    r"hiring alert|job alert|#jobopening|#jobs?\b|#careers?\b|#vacancy|#recruitment|#freshersjobs?|#fresherhiring)", re.I)
SEEKER_RX = re.compile(
    r"\b(i(?:'| a)?m (?:actively |currently )?(?:looking|seeking|searching|open to|on the lookout)|#opentowork|open to work|"
    r"open for (?:new )?opportunit|looking for (?:a |new |any |my )?(?:job|role|opportunit|position|internship|referral|full[- ]time)|"
    r"seeking (?:a |new |an )?(?:job|role|opportunit|position|internship)|i (?:have |had )?(?:recently |just )?(?:graduated|completed my)|"
    r"i (?:just |recently )?(?:got|received|accepted|joined|start(?:ed)? my|am joining|have joined)|happy to (?:share|announce)|"
    r"thrilled to (?:share|announce)|excited to (?:share|announce)|delighted to (?:share|announce)|proud to (?:share|announce)|"
    r"my (?:resume|cv) (?:is )?attached|please refer me|any referrals?\b|can (?:anyone|someone) refer|laid off|layoffs?\b|"
    r"looking for referrals?|kindly refer me|help me (?:find|get|land)|i am a (?:fresher|graduate|final year)|"
    r"i(?:'| a)?m a (?:fresher|graduate|final year)|actively seeking|immediate joiner looking|notice period.{0,20}looking)", re.I)
# A job seeker's own words. One of these anywhere outranks any number of #hiring hashtags, because
# seekers write "#Hiring #OpenToWork" in the same breath and recruiters never write these.
STRONG_SEEKER_RX = re.compile(
    r"(#opentowork|\bopen to work\b|i(?:'| a)?m (?:a |an )?(?:fresher|recent graduate|final[- ]year)|"
    r"looking for (?:an? )?(?:opportunit(?:y|ies)|chance|role|job|position|internship) (?:to|where i|in which i)\b|"
    r"my (?:resume|cv)\b|please refer me|kindly refer me|refer me\b|i(?:'| a)?m (?:actively |currently )?(?:looking|seeking|searching) for\b|"
    r"start my career|kick-?start my career|i (?:would|'d) (?:love|like) to (?:join|work|be part)|"
    r"#jobseeker|#jobsearch(?:ing)?\b|#lookingforjob|#needjob|open for (?:new )?opportunit)", re.I)
ROLE_RX = re.compile(
    r"\b(software (?:development )?engineers?|software developers?|software engineering|sde[- ]?(?:[123i]|intern)?\b|swe\b|sdet\b|"
    r"backend|back-end|frontend|front-end|full[- ]?stack|web developers?|java developers?|python developers?|\.net developers?|dotnet|"
    r"react(?:\.?js)? developers?|node(?:\.?js)? developers?|angular developers?|android developers?|ios developers?|flutter developers?|"
    r"mobile (?:app )?developers?|mern|mean stack|devops|cloud engineers?|data engineers?|ml engineers?|machine learning engineers?|"
    r"ai engineers?|qa engineers?|test engineers?|automation engineers?|programmers?|application developers?|"
    r"engineering (?:intern|trainee|graduate)|graduate engineer trainee|associate software|software trainee|"
    r"developer trainee|technical (?:intern|trainee))", re.I)
# "developer" / "engineer" on their own count only with a technology next to them
TECH_RX = re.compile(r"\b(java|python|c\+\+|c#|\.net|dotnet|javascript|typescript|react|angular|vue|node|spring|django|flask|sql|mysql|"
                     r"postgres|mongodb|aws|azure|gcp|docker|kubernetes|git|rest api|microservices|html|css|php|golang|\bgo\b|rust|kotlin|"
                     r"swift|flutter|dart|android|ios|linux|dsa|data structures|algorithms|oops|software|coding|programming|web|cloud|api)\b", re.I)
OFF_FIELD_RX = re.compile(r"\b(mechanical|civil|electrical|chemical|structural|process engineer|manufacturing|industrial|hardware|vlsi|embedded hardware|"
                          r"sales engineer|sales executive|business development|marketing|telecaller|bpo|customer (?:care|support|service)|hr executive|"
                          r"recruiter needed|accountant|nurse|teacher|driver|delivery)\b", re.I)
EXP_RANGE_RX = re.compile(r"(\d{1,2})(?:\.\d)?\s*(?:-|–|—|to)\s*(\d{1,2})(?:\.\d)?\s*\+?\s*(?:years?|yrs?|yoe)\b", re.I)
EXP_MIN_RX = re.compile(r"(?:minimum|min\.?|at ?least|more than|over|above)\s*(?:of\s*)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)|(\d{1,2})\s*\+\s*(?:years?|yrs?|yoe)", re.I)
EXP_EXACT_RX = re.compile(r"\b(\d{1,2})\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp\b)", re.I)
ENTRY_RX = re.compile(r"\b(freshers?|fresher'?s|entry[- ]level|new ?grads?|new graduates?|recent graduates?|fresh graduates?|"
                      r"graduates? (?:of |from )?20(?:2[3-7])|20(?:2[3-7]) (?:batch|pass[- ]?outs?|graduates?|grads|passouts)|"
                      r"batch (?:of )?20(?:2[3-7])|campus (?:hiring|drive|placement)|interns?hips?|\binterns?\b|trainees?|"
                      r"0\s*(?:-|–|to)\s*[123]\s*(?:years?|yrs?)|1\s*(?:-|–|to)\s*[23]\s*(?:years?|yrs?)|junior|\bjr\.?\s|early[- ]career|"
                      r"college graduates?|final[- ]year|pre[- ]final[- ]year|no experience|0 years?|zero experience|be\b|b\.?tech|b\.?e\b|mca\b|bca\b)", re.I)
SENIOR_RX = re.compile(r"\b(senior|\bsr\.?\s|lead\b|principal|staff engineer|architect|manager|head of|director|\bvp\b|"
                       r"[3-9]\s*\+\s*(?:years?|yrs?)|1\d\s*\+?\s*(?:years?|yrs?)|[3-9]\s*(?:-|–|to)\s*\d{1,2}\s*(?:years?|yrs?))", re.I)
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BATCH_RX = re.compile(r"\b(20(?:2[2-7]))\s*(?:batch|pass[- ]?outs?|graduates?|grads)|(?:batch|graduates?|grads) (?:of |from )?(20(?:2[2-7]))\b", re.I)
HASHTAG_RX = re.compile(r"#(\w{2,40})")
TIME_LABEL_RX = re.compile(r"(?<![\w$₹])(\d{1,3})\s*(mo|m|h|d|w|y)\b(?=\s*(?:•|·|ago|$|edited|\|))", re.I)
TIME_WORDS_RX = re.compile(r"(\d+)\s*(minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\s+ago|\b(just now|now)\b", re.I)

SKILLS = ["java", "python", "c++", "c#", ".net", "javascript", "typescript", "react", "angular", "vue", "node", "spring boot", "spring",
          "django", "flask", "fastapi", "sql", "mysql", "postgresql", "mongodb", "redis", "kafka", "aws", "azure", "gcp", "docker",
          "kubernetes", "git", "rest api", "microservices", "html", "css", "php", "laravel", "golang", "rust", "kotlin", "swift", "flutter",
          "dart", "android", "ios", "linux", "dsa", "data structures", "algorithms", "oops", "selenium", "cypress", "playwright", "devops",
          "ci/cd", "jenkins", "terraform", "graphql", "next.js", "express", "machine learning", "deep learning", "nlp", "tensorflow", "pytorch"]
_SKILL_RX = re.compile(r"(?<![a-z0-9+#.])(" + "|".join(re.escape(s) for s in sorted(SKILLS, key=len, reverse=True)) + r")(?![a-z0-9+#]|\.[a-z])", re.I)

# where: Indian cities first (most of these posts), then the usual hubs, then remote
PLACES = ["Bengaluru", "Bangalore", "Hyderabad", "Pune", "Chennai", "Mumbai", "Navi Mumbai", "Gurgaon", "Gurugram", "Noida", "Delhi", "NCR",
          "Kolkata", "Ahmedabad", "Jaipur", "Chandigarh", "Mohali", "Indore", "Bhopal", "Kochi", "Trivandrum", "Thiruvananthapuram",
          "Coimbatore", "Madurai", "Mysore", "Mysuru", "Nagpur", "Lucknow", "Bhubaneswar", "Vizag", "Visakhapatnam", "Vadodara", "Surat",
          "Dehradun", "Mangalore", "Hubli", "Trichy", "Vijayawada", "Patna", "Ranchi", "Guwahati", "Goa", "India", "Pan India",
          "Singapore", "Dubai", "Abu Dhabi", "London", "Berlin", "Amsterdam", "Dublin", "Toronto", "Sydney", "Melbourne", "Tokyo", "Bangkok",
          "Kuala Lumpur", "New York", "San Francisco", "Seattle", "Austin", "Remote", "Work from home", "WFH", "Hybrid", "Onsite", "On-site", "Work from office", "WFO"]
_PLACE_RX = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(p) for p in sorted(PLACES, key=len, reverse=True)) + r")(?![A-Za-z])", re.I)
_PLACE_CANON = {"bangalore": "Bengaluru", "gurugram": "Gurgaon", "mysuru": "Mysore", "visakhapatnam": "Vizag", "thiruvananthapuram": "Trivandrum",
                "work from home": "Remote", "wfh": "Remote", "on-site": "Onsite", "work from office": "Onsite", "wfo": "Onsite", "pan india": "India"}

LINKEDIN_EPOCH_SHIFT = 22   # the top bits of an activity / ugcPost id are the post's time in ms


def activity_time(activity_id) -> datetime | None:
    """When a post went up, exactly, from its id - LinkedIn ids carry the timestamp."""
    try:
        ms = int(str(activity_id)) >> LINKEDIN_EPOCH_SHIFT
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    if not (2015 <= dt.year <= 2100):
        return None
    return dt


def label_hours(text) -> float | None:
    """"3h" / "45m" / "1d" / "2w" / "3 hours ago" / "Just now" -> hours, or None when there is no age in it."""
    if not text:
        return None
    t = str(text)
    m = TIME_WORDS_RX.search(t)
    if m:
        if m.group(3):
            return 0.0
        n, unit = float(m.group(1)), m.group(2).lower()
        if unit.startswith("min"):
            return n / 60
        if unit.startswith(("hour", "hr")):
            return n
        if unit.startswith("day"):
            return n * 24
        if unit.startswith("week"):
            return n * 24 * 7
        return n * 24 * 30
    m = TIME_LABEL_RX.search(t)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    return {"m": n / 60, "h": n, "d": n * 24, "w": n * 24 * 7, "mo": n * 24 * 30, "y": n * 24 * 365}[unit]


def experience_of(text) -> dict:
    """{min, max, text, entry, senior} from a post's words about experience."""
    t = text or ""
    lo = hi = None
    found = ""
    m = EXP_RANGE_RX.search(t)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        found = m.group(0)
    else:
        m = EXP_MIN_RX.search(t)
        if m:
            lo = float(m.group(1) or m.group(2))
            found = m.group(0)
        else:
            m = EXP_EXACT_RX.search(t)
            if m:
                lo = hi = float(m.group(1))
                found = m.group(0)
    entry = bool(ENTRY_RX.search(t))
    senior = bool(SENIOR_RX.search(t))
    return {"min": lo, "max": hi, "text": found.strip(), "entry": entry, "senior": senior}


def fits_entry(exp: dict) -> bool:
    """Is this a post someone with 0-2 years can answer?

    Yes when it says so (freshers / entry level / 0-2 yrs / a recent batch / junior) or asks for
    at most 2 years; no when it asks for more than 2 or talks only in senior terms. A post that
    says nothing about experience at all is a yes - most hiring posts do not, and the reader
    decides.
    """
    lo = exp.get("min")
    if lo is not None and lo > 2:
        return False
    if exp.get("entry"):
        return True
    if lo is not None:
        return True
    return not exp.get("senior")


def classify(text: str, headline: str = "", open_to_work: bool = False) -> dict:
    """Everything the phone filters on, read from one post's text (and its author's headline).
    `open_to_work`: the author carries LinkedIn's Open-to-Work frame - a seeker, whatever the post says."""
    t = " ".join([text or ""])
    both = (headline or "") + " \n " + t
    hiring = bool(HIRING_RX.search(t))
    seeker = bool(SEEKER_RX.search(t))
    if open_to_work or STRONG_SEEKER_RX.search(t) or re.search(r"open to work|#opentowork|seeking (?:a |new )?(?:job|role|opportunit)", headline or "", re.I):
        seeker = True
    elif hiring and seeker:
        # a recruiter's post can contain "looking for a job?" - a weak seeker phrase on a hiring
        # post is outvoted when the hiring signals are the stronger set
        seeker = len(SEEKER_RX.findall(t)) > len(HIRING_RX.findall(t))
    roles = []
    for m in ROLE_RX.finditer(t):
        r = re.sub(r"\s+", " ", m.group(1).lower()).strip(" -")
        if r in ("developer", "developers", "engineer", "engineers", "programmer", "programmers", "coding", "programming") and not TECH_RX.search(t):
            continue
        r = re.sub(r"s$", "", r) if r.endswith(("developers", "engineers", "programmers")) else r
        if r not in roles:
            roles.append(r)
    # "GET" (Graduate Engineer Trainee) only in capitals - "get the details" is not a role
    if re.search(r"\bGET\b", t) and not any("trainee" in r for r in roles):
        roles.append("graduate engineer trainee")
    # a post about coding / developers that names a technology but no title still is a software post
    if not roles and re.search(r"\b(coding|programming|developers?|engineers?)\b", t, re.I) and TECH_RX.search(t):
        roles.append("software (general)")
    off_field = bool(OFF_FIELD_RX.search(t)) and not roles
    exp = experience_of(both)
    emails = []
    for e in EMAIL_RX.findall(t):
        e = e.strip(".").lower()
        if e not in emails and not e.endswith((".png", ".jpg")):
            emails.append(e)
    skills = []
    for m in _SKILL_RX.finditer(t):
        s = m.group(1).lower()
        if s not in skills:
            skills.append(s)
    places = []
    for m in _PLACE_RX.finditer(t):
        p = m.group(1)
        p = _PLACE_CANON.get(p.lower(), p[0].upper() + p[1:] if p.islower() else p)
        if p not in places:
            places.append(p)
    batch = []
    for m in BATCH_RX.finditer(t):
        y = m.group(1) or m.group(2)
        if y and y not in batch:
            batch.append(y)
    tags = [h.lower() for h in HASHTAG_RX.findall(t)][:15]
    salary = None
    try:
        sal = _salary_module()
        s = sal.find_in_text(t) if sal else None
        if s is not None:
            salary = s.to_dict()
    except Exception:  # noqa: BLE001 - pay is a bonus field
        salary = None
    fits = fits_entry(exp)
    score = (35 if hiring else 0) + (30 if roles else 0) + (25 if fits and (exp.get("entry") or exp.get("min") is not None) else (12 if fits else 0))
    score += 10 if (emails or batch) else 0
    if seeker:
        score -= 40
    if off_field:
        score -= 30
    return {"hiring": hiring, "seeker": seeker, "roles": roles[:8], "off_field": off_field, "exp": exp, "fits_entry": fits,
            "emails": emails[:6], "skills": skills[:14], "locations": places[:8], "batch": batch, "tags": tags, "salary": salary,
            "score": max(0, min(100, score))}


def wanted(info: dict) -> bool:
    """The posts the phone shows: a hiring post, for a software role, that fits 0-2 years."""
    return bool(info.get("hiring")) and not info.get("seeker") and bool(info.get("roles")) and not info.get("off_field") and bool(info.get("fits_entry"))


def _salary_module():
    """job-hunt's salary reader (jobbot/salary.py), when the sibling project is here."""
    scripts = ROOT.parent / "job-hunt" / "scripts"
    if not (scripts / "jobbot" / "salary.py").exists():
        return None
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from jobbot import salary as salary_mod  # type: ignore
        return salary_mod
    except Exception:  # noqa: BLE001
        return None


def good_links(links, author_url="") -> list[str]:
    """Links worth keeping from a post: application forms, career pages, shortlinks - not the
    author's own profile, LinkedIn's hashtags / search pages, or image URLs."""
    out = []
    for h in links or []:
        if not isinstance(h, str) or not h.startswith("http"):
            continue
        low = h.lower()
        if h == author_url:
            continue
        if "linkedin.com" in low and not re.search(r"linkedin\.com/(?:jobs/view|jobs/search|posts/|feed/update|company/[^/]+/jobs)", low):
            continue
        if re.search(r"\.(?:png|jpe?g|gif|webp|svg)(?:\?|$)", low) or "media.licdn.com" in low or "static.licdn.com" in low:
            continue
        if h not in out:
            out.append(h)
    return out[:8]


# ----------------------------------------------------------------------------- the browser side

# Reads every post card on a content-search page.
#
# LinkedIn's search renders posts with its new component framework (Oct 2026): hashed class
# names, no activity ids anywhere in the HTML, one `div[role="listitem"]` per result whose
# componentkey ("update-card-focus<key>FeedType_FLAGSHIP_SEARCH") carries a per-post key, the
# header as a run of <p>s (name, "• 3rd+", headline, "Just now" / "3h"), and the post text in a
# `[data-testid="expandable-text-box"]` that already holds the whole text (the "… more" is CSS).
# The post's own link is not in the page: the control menu's "Copy link to post" puts it on the
# clipboard, which copy_links() below reads for the posts worth keeping.
_EXTRACT_SDUI_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const timeRx = /^(just now|\d+\s*(?:m|h|d|w|mo|y)\b|\d+\s*(?:minutes?|hours?|days?|weeks?|months?)\s+ago)/i;
  const out = [];
  Array.from(document.querySelectorAll('div[role="listitem"]')).forEach((li, idx) => {
    const key = (li.getAttribute('componentkey') || '').replace(/^update-card-focus/, '').replace(/FeedType_[A-Za-z_]+$/, '');
    const box = li.querySelector('[data-testid="expandable-text-box"]');
    const boxText = norm(box ? box.innerText : '').replace(/\s*(…|\.\.\.)\s*more$/i, '');
    const ps = Array.from(li.querySelectorAll('p')).map(p => norm(p.innerText)).filter(Boolean);
    const header = [];
    for (const t of ps) {
      if (boxText && t.length > 30 && boxText.startsWith(t.slice(0, 30))) break;   // the text itself follows the header
      if (header.length >= 6) break;
      header.push(t);
    }
    const timeIdx = header.findIndex(t => timeRx.test(t));
    const head = timeIdx >= 0 ? header.slice(0, timeIdx) : header.slice(0, 3);
    const actorA = li.querySelector('a[href*="/in/"], a[href*="/company/"], a[href*="/school/"], a[href*="/showcase/"]');
    const author = head[0] || norm((li.querySelector('[aria-label^="View "]') || {}).getAttribute ? (li.querySelector('[aria-label^="View "]').getAttribute('aria-label') || '').replace(/^View /, '').replace(/[’']s profile.*$/, '') : '');
    const headline = head.filter((t, i) => i > 0 && !/^•/.test(t)).join(' · ');
    const links = Array.from(li.querySelectorAll('a[href]')).map(a => a.href).filter(h => /^https?:/.test(h));
    const full = norm(li.innerText || '');
    // LinkedIn's Open-to-Work frame shows up in the author's aria-labels ("X, Open to work 3rd+")
    const otw = Array.from(li.querySelectorAll('[aria-label]')).slice(0, 8).some(e => /open to work/i.test(e.getAttribute('aria-label') || ''))
             || Array.from(li.querySelectorAll('img[alt]')).slice(0, 3).some(e => /open to work/i.test(e.getAttribute('alt') || ''));
    out.push({ idx, id: key, author, headline, sub: timeIdx >= 0 ? header[timeIdx] : '', text: boxText,
               full: full.slice(0, 6000), links: Array.from(new Set(links)).slice(0, 40), actor_url: actorA ? actorA.href : '',
               counts: '', has_menu: !!li.querySelector('button[aria-label^="Open control menu"]'), open_to_work: otw });
  });
  return out;
}
"""

# The older feed markup (data-urn / feed-shared-update-v2 / update-components-*), kept as the
# fallback for the day LinkedIn serves it again.
_EXTRACT_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = [], seen = new Set(), cards = new Set();
  const sel = '[data-urn^="urn:li:activity:"],[data-id^="urn:li:activity:"],[data-urn^="urn:li:ugcPost:"],[data-id^="urn:li:ugcPost:"],' +
              'div.feed-shared-update-v2,[data-view-name="feed-full-update"],li.search-results__search-feed-update,div.update-components-update-v2,' +
              'div.occludable-update,li.reusable-search__result-container';
  document.querySelectorAll(sel).forEach(el => cards.add(el));
  document.querySelectorAll('a[href*="urn:li:activity:"],a[href*="/feed/update/"],a[href*="/posts/"]').forEach(a => {
    const c = a.closest('[data-urn],[data-id],div.feed-shared-update-v2,li,article');
    if (c) cards.add(c);
  });
  const all = Array.from(cards);
  const outer = all.filter(c => !all.some(o => o !== c && o.contains(c)));
  outer.forEach(card => {
    const html = card.outerHTML || '';
    const attr = (card.getAttribute('data-urn') || card.getAttribute('data-id') || '');
    let m = attr.match(/(?:activity|ugcPost|share):(\d{15,})/) || html.match(/urn:li:activity:(\d{15,})/) ||
            html.match(/activity-(\d{15,})-/) || html.match(/urn:li:ugcPost:(\d{15,})/) || html.match(/urn:li:share:(\d{15,})/);
    if (!m) return;
    const id = m[1];
    if (seen.has(id)) return;
    seen.add(id);
    const pick = (s) => { const el = card.querySelector(s); return el ? norm(el.innerText) : ''; };
    const author = pick('.update-components-actor__title span[aria-hidden="true"]') || pick('.update-components-actor__name') ||
                   pick('.update-components-actor__title') || pick('[data-view-name="feed-actor-name"]') || pick('.feed-shared-actor__name') ||
                   pick('.entity-result__title-text') || '';
    const headline = pick('.update-components-actor__description') || pick('.feed-shared-actor__description') ||
                     pick('[data-view-name="feed-actor-description"]') || pick('.entity-result__primary-subtitle') || '';
    const sub = pick('.update-components-actor__sub-description') || pick('.feed-shared-actor__sub-description') || '';
    const text = pick('.update-components-text') || pick('.feed-shared-update-v2__description') || pick('.feed-shared-inline-show-more-text') ||
                 pick('[data-view-name="feed-commentary"]') || pick('.feed-shared-text') || pick('.update-components-update-v2__commentary') || '';
    const links = Array.from(card.querySelectorAll('a[href]')).map(a => a.href).filter(h => /^https?:/.test(h));
    const actor = card.querySelector('.update-components-actor__meta-link, .update-components-actor__container a[href*="/in/"], .update-components-actor__container a[href*="/company/"], a[href*="/in/"], a[href*="/company/"]');
    const counts = norm((card.querySelector('.social-details-social-counts') || {}).innerText || '');
    const full = norm(card.innerText || '');
    out.push({ id, author, headline, sub, text, full: full.slice(0, 6000), links: Array.from(new Set(links)).slice(0, 40),
               actor_url: actor ? actor.href : '', counts });
  });
  return out;
}
"""

_EXPAND_JS = r"""
() => {
  let n = 0;
  document.querySelectorAll('button').forEach(b => {
    const t = (b.innerText || '').trim().toLowerCase();
    if (/^(…|\.\.\.)?\s*(see\s+)?more$/.test(t) || /see-more|show-more/.test(b.className || '')) { try { b.click(); n++; } catch (e) {} }
  });
  return n;
}
"""


def search_url(query: str, page_no: int = 1) -> str:
    from urllib.parse import urlencode
    params = {"keywords": query, "datePosted": '"past-24h"', "sortBy": '"date_posted"', "origin": "FACETED_SEARCH"}
    if page_no and page_no > 1:
        params["page"] = str(page_no)
    return SEARCH_URL + "?" + urlencode(params)


def fingerprint(author: str, text: str) -> str:
    """The same post seen twice (another query, another pass, a re-rendered key, a repost of the
    same text by someone else) has the same fingerprint. A long text is identity enough on its
    own; a short one needs the author too."""
    import hashlib
    body = re.sub(r"\W+", " ", (text or "").lower()).strip()
    base = body[:400] if len(body) >= 120 else re.sub(r"\W+", " ", (author or "").lower()).strip() + " " + body
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def author_posts_url(actor_url: str) -> str:
    """The author's own posts page - the post is at the top of it for hours after it went up."""
    u = (actor_url or "").split("?")[0]
    m = re.search(r"linkedin\.com/in/([^/]+)/?", u)
    if m:
        return f"https://www.linkedin.com/in/{m.group(1)}/recent-activity/all/"
    m = re.search(r"linkedin\.com/(company|school|showcase)/([^/]+)/?", u)
    if m:
        return f"https://www.linkedin.com/{m.group(1)}/{m.group(2)}/posts/"
    return u


def pause(lo=4.0, hi=9.0) -> None:
    time.sleep(random.uniform(lo, hi))


def _post_url(pid: str) -> str:
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{pid}/"


def _counts(text: str) -> tuple[int | None, int | None]:
    reactions = comments = None
    if text:
        m = re.search(r"(\d[\d,]*)\s*(?:reactions?|likes?|celebrates?|loves?)?", text)
        nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text)]
        if nums:
            reactions = nums[0]
        c = re.search(r"(\d[\d,]*)\s*comments?", text, re.I)
        if c:
            comments = int(c.group(1).replace(",", ""))
        del m
    return reactions, comments


def read_card(card: dict, query: str, now: datetime | None = None) -> dict | None:
    """A raw card from the page -> one post record (or None when there is nothing to read).

    The id is the activity id when the page had one (older markup), else the card's component
    key, else a fingerprint of author + text; the fingerprint is kept either way so the same
    post found through two queries is one post.
    """
    now = now or datetime.now(timezone.utc)
    text = (card.get("text") or "").strip()
    full = (card.get("full") or "").strip()
    author = (card.get("author") or "").strip()
    if not text:
        # no commentary block found: the whole card minus its first lines (actor, headline, time)
        text = re.sub(r"^\s*" + re.escape(author) + r".{0,200}?(?:\d+\s*[mhdw]\s*[•·]|ago|just now)\s*", "", full, count=1, flags=re.S | re.I) or full
    text = text[:3000]
    if not text and not author:
        return None
    fp = fingerprint(author, text)
    raw_id = str(card.get("id") or "").strip()
    pid = raw_id if raw_id.isdigit() else (raw_id if len(raw_id) >= 20 else fp)
    at = activity_time(pid) if pid.isdigit() else None
    label = card.get("sub") or ""
    age = label_hours(label) if label else None
    if age is None:
        age = label_hours(full[:400])
    if at is None and age is not None:
        at = now - timedelta(hours=age)
    info = classify(text, card.get("headline") or "", open_to_work=bool(card.get("open_to_work")))
    reactions, comments = _counts(card.get("counts") or "")
    author_url = card.get("actor_url") or ""
    # apply links are mostly written INTO the text ("Apply here: https://lnkd.in/..."), not rendered as anchors
    text_links = [u.rstrip(".,;:!?)") for u in re.findall(r"https?://[^\s<>\"'\]\)]+", text)]
    text_links += ["https://" + u for u in re.findall(r"(?<![\w/.])((?:lnkd\.in|bit\.ly|forms\.gle|tinyurl\.com|t\.ly|cutt\.ly)/[A-Za-z0-9_\-]+)", text)]
    if pid.isdigit():
        url, kind = _post_url(pid), "post"
    elif card.get("url"):
        url, kind = card["url"], "post"
    else:
        url, kind = author_posts_url(author_url), "author"
    rec = {
        "id": pid, "fp": fp, "url": url, "link_kind": kind, "author": author[:120], "author_url": author_url,
        "author_posts_url": author_posts_url(author_url), "open_to_work": bool(card.get("open_to_work")),
        "headline": (card.get("headline") or "")[:200], "posted_at": at.isoformat(timespec="seconds") if at else None,
        "age_label": label[:40], "text": text, "query": query, "queries": [query],
        "reactions": reactions, "comments": comments, "links": good_links(list(card.get("links") or []) + text_links, author_url),
        "first_seen": now.isoformat(timespec="seconds"), "last_seen": now.isoformat(timespec="seconds"),
    }
    rec.update(info)
    return rec


MAX_LINKS_PER_PAGE = 12


def copy_links(page, cards: list[dict], want: set, cap: int = MAX_LINKS_PER_PAGE) -> int:
    """Put each wanted post's own link on its card, through the control menu's "Copy link to post".

    One menu click and one item click per post (a couple of seconds each), read back from the
    clipboard (the browser context has clipboard permission). Posts without a link keep the
    author's posts page as their link. Returns how many links were read.
    """
    got = 0
    for card in cards:
        if got >= cap or card.get("idx") is None or card.get("id") not in want or not card.get("has_menu"):
            continue
        try:
            item = page.locator('div[role="listitem"]').nth(int(card["idx"]))
            btn = item.locator('button[aria-label^="Open control menu"]').first
            btn.scroll_into_view_if_needed(timeout=4000)
            btn.click(timeout=5000)
            page.wait_for_timeout(700)
            copy = page.get_by_role("menuitem", name=re.compile(r"copy link", re.I)).first
            if not copy.count():
                page.keyboard.press("Escape")
                continue
            copy.click(timeout=5000)
            page.wait_for_timeout(600)
            link = page.evaluate("() => navigator.clipboard.readText()") or ""
            if isinstance(link, str) and link.startswith("http") and "linkedin" in link.lower() or (isinstance(link, str) and link.startswith("https://lnkd.in/")):
                card["url"] = link.strip()
                got += 1
            time.sleep(random.uniform(0.6, 1.4))
        except Exception as exc:  # noqa: BLE001 - a link is a convenience; the post is kept either way
            log.debug("copy link failed for card %s: %s", card.get("idx"), str(exc)[:120])
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
    return got


def search_posts(page, query: str, scrolls: int = 2, debug: bool = False, page_no: int = 1, links: bool = True,
                 now: datetime | None = None) -> list[dict]:
    """One content-search page for `query`, newest first, last 24 h -> raw cards (with each
    wanted post's own link copied onto it when `links`)."""
    from . import linkedin as linkedin_mod
    url = search_url(query, page_no)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4500)
    if not linkedin_mod.is_logged_in(page, strict=True):
        raise linkedin_mod.NotLoggedIn("LinkedIn content search needs the saved session - run: python main.py --linkedin-login")
    for _ in range(scrolls):
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        except Exception:  # noqa: BLE001
            break
        page.wait_for_timeout(random.randint(1500, 2500))
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.evaluate(_EXPAND_JS)
        page.wait_for_timeout(800)
    except Exception:  # noqa: BLE001
        pass
    cards = page.evaluate(_EXTRACT_SDUI_JS) or []
    markup = "sdui"
    if not cards:
        cards = page.evaluate(_EXTRACT_JS) or []
        markup = "feed"
    if debug:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:50] + (f"-p{page_no}" if page_no > 1 else "")
        try:
            (DEBUG_DIR / f"debug-{slug}.html").write_text(page.content(), encoding="utf-8")
            (DEBUG_DIR / f"debug-{slug}.json").write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("debug dump failed: %s", exc)
    copied = 0
    if links and markup == "sdui" and cards:
        # only the posts the phone will show get the extra clicks for their link
        want = set()
        for c in cards:
            rec = read_card(c, query, now)
            if rec and wanted(rec) and not c.get("id", "").isdigit():
                want.add(c.get("id"))
        copied = copy_links(page, cards, want)
    log.info("  posts %-48s p%d %3d card(s) (%s)%s", query, page_no, len(cards), markup, f", {copied} link(s) copied" if copied else "")
    return cards


# ----------------------------------------------------------------------------- the store

def load_store(path: Path = STORE_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("posts"), list):
            data.setdefault("cursor", 0)
            return data
    except (OSError, ValueError):
        pass
    return {"updated": None, "window_hours": WINDOW_HOURS, "queries": [], "cursor": 0, "pc": {}, "posts": []}


def save_store(store: dict, path: Path = STORE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def merge(store: dict, posts: list[dict], now: datetime | None = None, keep_hours: float = KEEP_HOURS) -> int:
    """Fold freshly read posts into the store (one entry per post id); drop what is older than keep_hours.
    Returns how many were new."""
    now = now or datetime.now(timezone.utc)
    by_id = {p["id"]: p for p in store.get("posts") or [] if isinstance(p, dict) and p.get("id")}
    by_fp = {p["fp"]: p for p in by_id.values() if p.get("fp")}
    new = 0
    for p in posts:
        if not p or not p.get("id"):
            continue
        old = by_id.get(p["id"]) or (by_fp.get(p["fp"]) if p.get("fp") else None)
        if old is None:
            by_id[p["id"]] = p
            if p.get("fp"):
                by_fp[p["fp"]] = p
            new += 1
            continue
        if p.get("url") and p.get("link_kind") == "post" and old.get("link_kind") != "post":
            old["url"], old["link_kind"] = p["url"], "post"      # a link we did not have before
        qs = list(old.get("queries") or [])
        for q in p.get("queries") or []:
            if q not in qs:
                qs.append(q)
        keep_link = old.get("link_kind") == "post" and p.get("link_kind") != "post"
        old.update({k: v for k, v in p.items() if k not in ("first_seen", "queries", "query", "id", "posted_at")
                    and not (keep_link and k in ("url", "link_kind"))})
        old["posted_at"] = old.get("posted_at") or p.get("posted_at")      # the first reading is the closest to the truth
        old["queries"] = qs
        old["last_seen"] = p.get("last_seen") or now.isoformat(timespec="seconds")
    cutoff = now - timedelta(hours=keep_hours)
    kept = []
    for p in by_id.values():
        at = _parse_iso(p.get("posted_at")) or _parse_iso(p.get("first_seen"))
        if at is None or at >= cutoff:
            kept.append(p)
    kept.sort(key=lambda p: p.get("posted_at") or p.get("first_seen") or "", reverse=True)
    store["posts"] = kept
    return new


def _parse_iso(s) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def payload_for(store: dict, hours: float = WINDOW_HOURS, now: datetime | None = None, limit: int = MAX_PUBLISHED) -> dict:
    """What the phone gets: the wanted posts from the last `hours`, newest first, ages filled in."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    out = []
    for p in store.get("posts") or []:
        at = _parse_iso(p.get("posted_at"))
        if at is None or at < cutoff:
            continue
        # judged again with today's rules, so a post read before a rule changed is not stuck with the old verdict
        if p.get("text"):
            p.update(classify(p["text"], p.get("headline") or "", open_to_work=bool(p.get("open_to_work"))))
        if not wanted(p):
            continue
        q = dict(p)
        q["hours_old"] = round((now - at).total_seconds() / 3600, 2)
        q.pop("full", None)
        out.append(q)
    out.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
    return {
        "updated": store.get("updated") or now.isoformat(timespec="seconds"),
        "window_hours": hours, "every_minutes": store.get("every_minutes") or EVERY_MINUTES,
        "queries": store.get("queries") or [], "pc": store.get("pc") or {},
        "count": len(out), "seen_total": len(store.get("posts") or []),
        "posts": out[:limit],
    }


def load_queries() -> list[str]:
    """QUERIES, unless data/posts/queries.txt has a list of its own."""
    path = DEBUG_DIR / "queries.txt"
    try:
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
        custom = [l for l in lines if l and not l.startswith("#")]
        if custom:
            return custom
    except OSError:
        pass
    return list(QUERIES)


# ----------------------------------------------------------------------------- publishing

def publish(payload: dict) -> bool:
    """Write the payload to the gh-pages branch through the GitHub API (site/tools/pages_git.put_file).
    No clone is touched, so this never collides with the queue run working in its clone."""
    tools = ROOT.parent / "site" / "tools"
    if not (tools / "pages_git.py").exists():
        log.warning("publish skipped: %s not found", tools)
        return False
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import pages_git  # type: ignore
        repo_url = None
        try:
            from phone_publish import load_config  # type: ignore
            repo_url = (load_config() or {}).get("repo_url")
        except (SystemExit, Exception):  # noqa: BLE001 - no phone config: the repo's own remote
            repo_url = None
        repo_url = repo_url or pages_git.default_repo_url()
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        pages_git.put_file(repo_url, PUBLISH_PATH, text,
                           "linkedin posts: %d hiring post(s) in the last %gh" % (payload.get("count", 0), payload.get("window_hours", WINDOW_HOURS)))
        return True
    except (SystemExit, Exception) as exc:  # noqa: BLE001 - the phone shows the last good copy meanwhile
        log.warning("publish failed: %s", str(exc)[:300])
        return False


# ----------------------------------------------------------------------------- a pass, and the loop

def run_once(hours: float = WINDOW_HOURS, headless: bool = True, per_pass: int = PER_PASS, debug: bool = False,
             queries: list[str] | None = None, do_publish: bool = True, store_path: Path = STORE_PATH) -> dict:
    """One pass: search the next `per_pass` queries, merge, save, publish. Returns the published payload."""
    from playwright.sync_api import sync_playwright

    from . import linkedin as linkedin_mod

    store = load_store(store_path)
    all_queries = queries or load_queries()
    cursor = int(store.get("cursor") or 0) % max(1, len(all_queries))
    batch = [all_queries[(cursor + i) % len(all_queries)] for i in range(min(per_pass, len(all_queries)))]
    store["queries"] = all_queries
    store["window_hours"] = hours
    now = datetime.now(timezone.utc)
    read, wanted_n, errors = [], 0, []
    t0 = time.time()
    with sync_playwright() as p:
        browser, ctx, page = linkedin_mod.open_session(p, headless=headless)
        try:
            try:
                ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://www.linkedin.com")
            except Exception as exc:  # noqa: BLE001 - then posts link to their author's posts page instead
                log.debug("clipboard permission not granted: %s", exc)
            for i, q in enumerate(batch):
                try:
                    cards = search_posts(page, q, debug=debug, now=now)
                except linkedin_mod.NotLoggedIn:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad page must not end the pass
                    errors.append(f"{q}: {str(exc)[:120]}")
                    log.warning("  posts %-48s failed: %s", q, str(exc)[:160])
                    cards = []
                for c in cards:
                    rec = read_card(c, q, now)
                    if rec:
                        read.append(rec)
                        if wanted(rec):
                            wanted_n += 1
                if i < len(batch) - 1:
                    pause()
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
    new = merge(store, read, now)
    store["cursor"] = (cursor + len(batch)) % len(all_queries)
    store["updated"] = now.isoformat(timespec="seconds")
    pc = store.setdefault("pc", {})
    pc.update({"host": os.environ.get("COMPUTERNAME", ""), "last_pass": store["updated"], "passes": int(pc.get("passes") or 0) + 1,
               "last_queries": batch, "last_read": len(read), "last_new": new, "last_errors": errors[:5], "last_error": "",
               "seconds": round(time.time() - t0, 1)})
    save_store(store, store_path)
    payload = payload_for(store, hours, now)
    log.info("pass done: %d card(s) read, %d new, %d hiring post(s) for 0-2 yrs in the last %gh (%.0fs)%s",
             len(read), new, payload["count"], hours, time.time() - t0, f"; {len(errors)} query error(s)" if errors else "")
    if do_publish:
        publish(payload)
    return payload


def _note_error(message: str, hours: float, store_path: Path = STORE_PATH, do_publish: bool = True) -> None:
    """Tell the phone what stopped the watcher (an expired login, mostly)."""
    store = load_store(store_path)
    pc = store.setdefault("pc", {})
    pc.update({"host": os.environ.get("COMPUTERNAME", ""), "last_error": message, "last_error_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    store["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_store(store, store_path)
    if do_publish:
        publish(payload_for(store, hours))


def loop(every_minutes: int = EVERY_MINUTES, hours: float = WINDOW_HOURS, headless: bool = True, per_pass: int = PER_PASS,
         debug: bool = False) -> int:
    """Pass after pass, for as long as this process lives (Task Scheduler starts it at logon and
    starts it again if it ever stops). An expired LinkedIn login is reported to the phone and
    retried every hour - sign in again with `python main.py --linkedin-login`."""
    from . import linkedin as linkedin_mod
    log.info("LinkedIn hiring-posts watcher: every %d min, posts from the last %gh, %d queries a pass, %s",
             every_minutes, hours, per_pass, "headless" if headless else "visible browser")
    while True:
        started = time.time()
        wait = every_minutes * 60
        try:
            run_once(hours=hours, headless=headless, per_pass=per_pass, debug=debug)
        except linkedin_mod.NotLoggedIn as exc:
            log.error("%s", exc)
            _note_error(str(exc), hours)
            wait = 60 * 60
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001 - never let one bad pass end the watcher
            log.exception("pass failed: %s", exc)
            _note_error(f"pass failed: {str(exc)[:200]}", hours)
        # the gap is measured from the START of the pass, with a little jitter so it never looks like clockwork
        sleep_for = max(60, wait - (time.time() - started) + random.uniform(-180, 180))
        log.info("next pass in %.0f min", sleep_for / 60)
        time.sleep(sleep_for)


def _setup_logging(verbose: bool) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", handlers=handlers)
    for noisy in ("naukri.jobs.linkedin", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.INFO)


def _guard_children() -> None:
    """Every browser this process starts dies with it (scripts/jobguard.py's job object), so a
    watcher stopped from Task Scheduler never leaves a headless Chrome behind."""
    guard = ROOT / "scripts" / "jobguard.py"
    if os.name != "nt" or not guard.exists():
        return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("jobguard", str(guard))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)   # type: ignore[union-attr]
        mod.kill_tree_on_exit()
    except Exception as exc:  # noqa: BLE001 - only the cleanup is lost
        log.debug("job object not set up: %s", exc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="one pass, then exit")
    mode.add_argument("--loop", action="store_true", help="a pass every --every minutes, for as long as the PC is on")
    mode.add_argument("--publish-only", action="store_true", dest="publish_only", help="publish what the store has, no browsing")
    ap.add_argument("--every", type=int, default=EVERY_MINUTES, metavar="MIN", help=f"minutes between passes (default {EVERY_MINUTES})")
    ap.add_argument("--hours", type=float, default=WINDOW_HOURS, metavar="N", help=f"the window the phone shows (default {WINDOW_HOURS})")
    ap.add_argument("--per-pass", type=int, default=PER_PASS, dest="per_pass", metavar="N", help=f"queries per pass (default {PER_PASS})")
    ap.add_argument("--query", action="append", help="search only this query (repeatable; default: the built-in list)")
    ap.add_argument("--show", action="store_true", help="visible browser (default: headless, nothing on screen)")
    ap.add_argument("--debug", action="store_true", help="save each result page's HTML and cards under data/posts/")
    ap.add_argument("--no-publish", action="store_true", dest="no_publish", help="do not push to the phone site")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    _setup_logging(args.verbose)
    if args.show:
        os.environ["NAUKRI_SHOW"] = "1"
        os.environ.pop("NAUKRI_BACKGROUND", None)
    else:
        os.environ["NAUKRI_BACKGROUND"] = "1"      # naukri/session.py: headless, no window ever
    _guard_children()
    _keep_awake()
    if args.publish_only:
        return 0 if publish(payload_for(load_store(), args.hours)) else 1
    if args.loop:
        return loop(args.every, args.hours, headless=not args.show, per_pass=args.per_pass, debug=args.debug)
    from . import linkedin as linkedin_mod
    try:
        payload = run_once(hours=args.hours, headless=not args.show, per_pass=args.per_pass, debug=args.debug,
                           queries=args.query, do_publish=not args.no_publish)
    except linkedin_mod.NotLoggedIn as exc:
        print(f"\n  {exc}\n")
        _note_error(str(exc), args.hours, do_publish=not args.no_publish)
        return 2
    print(f"\n  {payload['count']} hiring post(s) for 0-2 yrs in the last {args.hours:g} h "
          f"({payload['seen_total']} posts remembered). Store: {STORE_PATH}\n")
    for p in payload["posts"][:12]:
        print(f"  {p['hours_old']:>5.1f}h  {', '.join(p.get('roles') or [])[:34]:<34} {p.get('exp', {}).get('text') or ('fresher' if p.get('exp', {}).get('entry') else '-'):<12} {p['author'][:28]:<28} {p['url']}")
    return 0


def _keep_awake():
    """The PC may still blank its screen, but it does not sleep while the watcher runs."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
