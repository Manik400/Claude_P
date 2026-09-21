"""Find the job board a company really uses, when the one in companies.txt does not answer.

A slug in companies.txt is a guess until a board answers to it, and guesses rot: a company
moves from Greenhouse to Ashby, renames its board, or never had one. That used to end a
company's row in `404 Not Found` and no jobs. Now a row that fails is re-resolved here, in
the order that costs the least and lies the least:

    1. the careers link in the row      https://jobs.ashbyhq.com/openai -> ashby/openai, used as given
    2. that link's page                 a company's own /careers page names its board in the HTML
    3. the company name                 slug variants probed against every job-board API
    4. the local model (Ollama)         asked for the careers URL / board slug - then *verified* like
                                        any other guess, never trusted on its own
    5. a LinkedIn company search        nothing answered: the report still gets a link a human can click

What answers is written to assets/boards_cache.json, so the next run goes straight to it,
and `careers_bot.py resolve --write` folds the findings back into companies.txt.
"""
import json
import os
import re
import time
from urllib.parse import urlparse

from ..textutil import slugify
from .companies import Company

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "assets", "boards_cache.json")
OK_TTL = 30 * 86400      # a board that answered is re-checked monthly
MISS_TTL = 7 * 86400     # a company nothing was found for is retried weekly
THIN_BOARD = 3           # a board with fewer open jobs than this is kept, but not stopped at

# --------------------------------------------------------------- URL -> board

_URL_RULES = [
    ("greenhouse", re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([A-Za-z0-9_.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers|api)\.smartrecruiters\.com/(?:v1/companies/)?([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([A-Za-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"https?://([A-Za-z0-9_-]+)\.recruitee\.com", re.I)),
]
# <sub>.wdN.myworkdayjobs.com, then - in any of the shapes Workday hands out - an optional
# wday/cxs prefix, an optional locale, and one or two path segments: <site> alone (the tenant is
# then the subdomain) or <tenant>/<site>.
_WORKDAY_RE = re.compile(r"([A-Za-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/)?"
                         r"(?:[a-z]{2}-[A-Za-z]{2}/)?([A-Za-z0-9_-]+)(?:/([A-Za-z0-9_-]+))?", re.I)
# Path segments that follow a site and are not a site themselves.
_WORKDAY_TAIL = {"job", "jobs", "details", "login", "search", "home", "apply"}
# Slugs the patterns above would happily read out of a generic URL but that are never a board.
_NOT_A_BOARD = {"embed", "job_board", "jobs", "careers", "search", "api", "v1", "companies", "www", "en", "en-us"}


def from_url(url):
    """('greenhouse', 'agoda') for a URL that names a board, else (None, None)."""
    if not url or "://" not in url:
        return None, None
    m = _WORKDAY_RE.search(url)
    if m:
        sub, wd, first, second = m.group(1), m.group(2), m.group(3), m.group(4)
        if second and second.lower() not in _WORKDAY_TAIL:
            tenant, site = first, second
        else:
            tenant, site = sub, first
        return "workday", f"{sub}.{wd}.myworkdayjobs.com/{tenant}/{site}"
    for ats, rx in _URL_RULES:
        m = rx.search(url)
        if m and m.group(1).lower() not in _NOT_A_BOARD:
            return ats, m.group(1)
    return None, None


def is_board_url(url):
    return from_url(url)[0] is not None


# ---------------------------------------------------------- slug candidates

_SUFFIX = re.compile(r"\b(?:inc|ltd|llc|plc|gmbh|bv|nv|ag|sa|se|technologies|technology|labs|group|"
                     r"global|holdings|systems|solutions|software|company|corp|corporation)\b", re.I)


def slug_variants(name, url=None, extra=()):
    """Slugs worth probing for a company: 'Weights & Biases' -> weightsbiases, weights-biases, weights, wandb(extra)."""
    base = _SUFFIX.sub(" ", name or "")
    base = re.split(r"\s*[/(|]", base)[0]                      # 'TikTok / ByteDance' -> 'TikTok'
    base = re.sub(r"\band\b", " ", base, flags=re.I)
    s = slugify(base)
    flat = s.replace("-", "")
    # ...usa / ...inc / ...careers are how a taken slug gets taken again: DoorDash is `doordashusa`.
    out = [flat, s, s.split("-")[0] if s else ""] + [flat + tail for tail in
                                                    ("usa", "inc", "ai", "hq", "global", "jobs", "careers", "group")]
    for host in _hosts(url):
        out.append(host)
        out.append(host.replace("-", ""))
    out.extend(extra or ())
    seen, keep = set(), []
    for v in out:
        v = (v or "").strip().lower()
        if v and len(v) > 1 and v not in seen and v not in _NOT_A_BOARD:
            seen.add(v)
            keep.append(v)
    return keep


def _hosts(url):
    """'https://careers.snowflake.com/x' -> ['snowflake'] - the registrable name, minus www/careers/jobs."""
    if not url or "://" not in url:
        return []
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    parts = [p for p in host.split(".") if p not in ("www", "careers", "career", "jobs", "job", "apply", "com", "org",
                                                     "net", "io", "co", "ai", "de", "nl", "uk", "fr", "in", "sg", "jp")]
    return parts[:1]


# ------------------------------------------------------------- verification

def verify(http, ats, board, timeout_retries=0):
    """How many jobs that board has open, or None when it does not answer. Never raises."""
    try:
        if ats == "greenhouse":
            d = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", retries=timeout_retries)
            return len(d.get("jobs") or [])
        if ats == "lever":
            d = http.get_json(f"https://api.lever.co/v0/postings/{board}?mode=json", retries=timeout_retries)
            return len(d) if isinstance(d, list) else None
        if ats == "ashby":
            d = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}", retries=timeout_retries)
            return len(d.get("jobs") or [])
        if ats == "smartrecruiters":
            d = http.get_json(f"https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=1",
                              retries=timeout_retries)
            return int(d.get("totalFound") or 0)
        if ats == "recruitee":
            d = http.get_json(f"https://{board}.recruitee.com/api/offers/", retries=timeout_retries)
            return len(d.get("offers") or [])
        if ats == "workable":
            d = http.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{board}?details=true",
                              retries=timeout_retries)
            return len(d.get("jobs") or [])
        if ats == "workday":
            host, tenant, site = board.split("/", 2)
            r = http.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                          json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, retries=timeout_retries)
            if r.status_code != 200:
                return None
            d = r.json()
            return int(d.get("total") or 0) or len(d.get("jobPostings") or [])
    except Exception:  # noqa: BLE001 - a miss is the normal answer here
        return None
    return None


PROBE_ORDER = ("greenhouse", "ashby", "lever", "smartrecruiters", "workable", "recruitee")


def probe_slug(http, slug, order=PROBE_ORDER):
    """First board that answers for this slug -> (ats, open jobs), else None."""
    for ats in order:
        n = verify(http, ats, slug)
        if n:
            return ats, n
    return None


# --------------------------------------------------- whose board is this?
# A guessed slug is not enough: meta.recruitee.com answers, with the jobs of
# Addis Ababa University. Every board found by guessing is asked whose it is,
# and dropped when the answer is somebody else. Boards pinned in companies.txt
# (a link, or a slug that still answers) are taken as given - that is the point
# of pinning one.

def owner(http, ats, board):
    """The company name a board belongs to, or '' when the board does not say."""
    try:
        if ats == "greenhouse":
            return (http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}", retries=0) or {}).get("name") or ""
        if ats == "workable":
            d = http.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{board}", retries=0) or {}
            return d.get("name") or ""
        if ats == "recruitee":
            d = http.get_json(f"https://{board}.recruitee.com/api/offers/", retries=0) or {}
            return ((d.get("offers") or [{}])[0]).get("company_name") or ""
        if ats == "smartrecruiters":
            d = http.get_json(f"https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=1", retries=0) or {}
            return (((d.get("content") or [{}])[0]).get("company") or {}).get("name") or ""
        if ats in ("ashby", "lever"):
            url = f"https://jobs.ashbyhq.com/{board}" if ats == "ashby" else f"https://jobs.lever.co/{board}"
            r = http.get(url, retries=0, allow_block=True)
            m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:20000], re.S | re.I)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            return re.sub(r"\s*(?:\||-|–)?\s*(?:jobs|careers|job board|open roles)\s*$", "", title, flags=re.I)
    except Exception:  # noqa: BLE001 - no answer is the same as no name
        return ""
    return ""


def _compact(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def aliases(name):
    """'TikTok / ByteDance' -> ['tiktok', 'bytedance']; suffixes like Inc/GmbH dropped."""
    out = []
    for part in re.split(r"\s*[/|]\s*|,\s*", name or ""):
        part = _SUFFIX.sub(" ", part)
        c = _compact(part)
        if len(c) >= 3:
            out.append(c)
    return out or [_compact(name)]


def same_company(name, board_owner):
    """Is this board the one belonging to `name`? Unknown owner -> None (undecided)."""
    if not board_owner:
        return None
    them = aliases(board_owner)
    for us in aliases(name):
        for they in them:
            if us == they or (len(us) >= 4 and us in they) or (len(they) >= 4 and they in us):
                return True
    return False


# ------------------------------------------------------ reading a career page

_PAGE_HINTS = re.compile(r"(?:boards|job-boards)\.(?:eu\.)?greenhouse\.io/[A-Za-z0-9_-]+"
                         r"|greenhouse\.io/embed/job_board[^\"'<> ]*for=[A-Za-z0-9_-]+"
                         r"|jobs\.(?:eu\.)?lever\.co/[A-Za-z0-9_-]+"
                         r"|jobs\.ashbyhq\.com/[A-Za-z0-9_.-]+"
                         r"|jobs\.smartrecruiters\.com/[A-Za-z0-9_-]+"
                         r"|apply\.workable\.com/[A-Za-z0-9_-]+"
                         r"|[A-Za-z0-9_-]+\.recruitee\.com"
                         r"|[A-Za-z0-9-]+\.wd\d+\.myworkdayjobs\.com/[^\"'<> ]+", re.I)


def from_page(http, url):
    """Fetch a company's own careers page and read the board out of its HTML -> (ats, board) or (None, None).

    Career pages are built on these boards, so the board's URL is almost always in the markup -
    an iframe, a "see all jobs" link or the widget's script tag.
    """
    if not url or "://" not in url:
        return None, None
    try:
        r = http.get(url, retries=0, allow_block=True)
        if r.status_code >= 400:
            return None, None
        body = r.text[:400000]
    except Exception:  # noqa: BLE001
        return None, None
    for hit in _PAGE_HINTS.findall(body):
        ats, board = from_url("https://" + hit.lstrip("/") if "://" not in hit else hit)
        if ats:
            return ats, board
    return None, None


# --------------------------------------------------------------- the local AI

def ai_suggestions(name, note=""):
    """Slugs / careers URLs the local model (Ollama, else the bundled GGUF) thinks this company uses.

    Only ever a *shortlist to verify*: a model that invents a slug costs one HEAD request here,
    it never reaches the company list, because every suggestion goes through verify() first.
    """
    try:
        from .. import localai
    except Exception:  # noqa: BLE001
        return {}
    if not localai.available("llm") or localai.budget_left() < 10:
        return {}
    out = localai.ask(
        'Company: "%s"%s\n'
        "Which applicant tracking system hosts its job board, and under which id?\n"
        'Answer JSON only: {"ats": "greenhouse|lever|ashby|smartrecruiters|workable|recruitee|workday|unknown", '
        '"slug": "<the id in the board URL, lowercase, no spaces>", '
        '"careers_url": "<its careers page URL>", "other_slugs": ["<alternative ids>"]}'
        % (name, (" (%s)" % note[:80]) if note else ""),
        system="You know company career pages. Answer only with the JSON object. Use \"unknown\" when unsure.",
        json=True, max_tokens=160, timeout=25)
    if not isinstance(out, dict):
        return {}
    slugs = [str(out.get("slug") or "")] + [str(s) for s in (out.get("other_slugs") or [])][:3]
    return {"ats": str(out.get("ats") or "").lower().strip(),
            "slugs": [re.sub(r"[^a-z0-9._-]", "", s.lower()) for s in slugs if s],
            "careers_url": str(out.get("careers_url") or "").strip()}


# ---------------------------------------------------------------- the cache

def load_cache(path=None):
    try:
        with open(path or CACHE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache, path=None):
    path = path or CACHE_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError:
        pass


def cached(cache, name):
    """A cache entry that is still fresh, else None."""
    e = cache.get((name or "").lower())
    if not e:
        return None
    ttl = OK_TTL if e.get("ats") else MISS_TTL
    return e if time.time() - float(e.get("checked") or 0) < ttl else None


def linkedin_search(name):
    """Last resort: the company's jobs on LinkedIn - not an API, but a link that works."""
    return "https://www.linkedin.com/jobs/search/?keywords=" + re.sub(r"\s+", "%20", (name or "").strip())


# ------------------------------------------------------------------ resolve

def resolve(http, name, url="", note="", use_ai=True, cache=None, log=None, hint_ats="", hint_board=""):
    """Find a working board for one company.

    -> {"ats": ..., "board": ..., "url": ..., "jobs": N, "via": "..."}   a board that answered
       {"ats": "", "board": "", "url": <careers or LinkedIn link>, "via": "link"}   nothing answered

    `hint_ats`/`hint_board` are what companies.txt says today: they are tried first, so a row
    that is merely slow (not wrong) keeps its slug.
    """
    say = log or (lambda *a: None)
    key = (name or "").lower()
    if cache is not None:
        hit = cached(cache, key)
        if hit:
            return dict(hit, via=hit.get("via", "cache") + "+cache")

    def done(ats, board, via, jobs, page_url=""):
        out = {"ats": ats, "board": board, "url": page_url or Company(name, ats, board).careers,
               "jobs": jobs, "via": via, "checked": time.time()}
        if cache is not None:
            cache[key] = out
        say(f"  resolved {name}: {ats}/{board} ({jobs} open) via {via}")
        return out

    # 1. the link in the row, when it is a board URL: strictly what the file says
    ats, board = from_url(url)
    if ats:
        n = verify(http, ats, board)
        if n:
            return done(ats, board, "link", n, url)
        say(f"  {name}: the link in companies.txt ({ats}/{board}) did not answer")

    # 2. what companies.txt claims today
    if hint_ats and hint_board:
        n = verify(http, hint_ats, hint_board)
        if n:
            return done(hint_ats, hint_board, "companies.txt", n)

    # 3. the careers page named in the row, read for the board it embeds
    if url and not ats:
        ats2, board2 = from_page(http, url)
        n = verify(http, ats2, board2) if ats2 else None
        if n:
            return done(ats2, board2, "careers page", n, url)

    # 4. slug variants of the name, across every board API - each one asked whose board it is
    order = (hint_ats,) + tuple(a for a in PROBE_ORDER if a != hint_ats) if hint_ats in PROBE_ORDER else PROBE_ORDER
    # A slug can answer with a board that is real but empty - Uber's SmartRecruiters account holds
    # one "Test UAT" posting while the jobs are elsewhere. So a thin hit is not the end of the
    # search: the remaining variants are tried and the fullest board wins.
    rejected, best = [], None
    for slug in slug_variants(name, url)[:8]:
        hit = probe_slug(http, slug, order)
        if not hit:
            continue
        whose = owner(http, hit[0], slug)
        if same_company(name, whose) is False:
            rejected.append(f"{hit[0]}/{slug} belongs to {whose}")
            continue
        candidate = (hit[1], hit[0], slug, "name" if whose else "name (unconfirmed)")
        if best is None or candidate[0] > best[0]:
            best = candidate
        if best[0] >= THIN_BOARD:
            break
    for r in rejected:
        say(f"  {name}: skipped {r}")
    if best:
        return done(best[1], best[2], best[3], best[0])

    # 5. ask the local model, then verify whatever it says
    if use_ai:
        s = ai_suggestions(name, note)
        for slug in (s.get("slugs") or [])[:4]:
            guess = s.get("ats") if s.get("ats") in PROBE_ORDER else None
            hit = probe_slug(http, slug, (guess,) + tuple(a for a in PROBE_ORDER if a != guess) if guess else PROBE_ORDER)
            if hit and same_company(name, owner(http, hit[0], slug)) is not False:
                return done(hit[0], slug, "local AI", hit[1])
        ai_url = s.get("careers_url") or ""
        ats3, board3 = from_url(ai_url)
        if not ats3 and ai_url:
            ats3, board3 = from_page(http, ai_url)
        if ats3:
            n = verify(http, ats3, board3)
            if n:
                return done(ats3, board3, "local AI page", n, ai_url)

    out = {"ats": "", "board": "", "url": url or linkedin_search(name), "jobs": 0,
           "via": "link" if url else "linkedin", "checked": time.time()}
    if cache is not None:
        cache[key] = out
    return out
