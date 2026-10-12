"""What a job pays, in LPA, when the posting does not say - looked up once, remembered.

    from jobbot import salary_lookup
    est = salary_lookup.estimate("SDE 1", "Amazon Development Centre")
    # {"lpa": 20.0, "lo": 12.0, "hi": 28.0, "kind": "typical", "source": "typical for Amazon (big tech)", "url": ...}
    salary_lookup.annotate_jobs(jobs, log=print)      # job-hunt Job objects: extra.lpa / extra.lpa_kind / extra.is_mnc ...

Order, cheapest first, the first answer wins and is cached for 60 days
(~/Documents/JobHunt/salary_cache.json, shared by both projects):
  1. the company's typical band for 0-2 years from assets/mnc.txt          kind "typical"
  2. a web search for "<company> <role> salary India LPA" (Firecrawl,
     FIRECRAWL_API_KEY): figures in the snippets of AmbitionBox, Glassdoor,
     levels.fyi, PayScale ... are read with jobbot.salary and the median taken  kind "web"
  3. JSearch's estimated-salary for the role in India (RAPIDAPI_KEY),
     not company-specific                                                      kind "role"
Every run has a budget of lookups (SALARY_LOOKUPS_PER_RUN, default 12 web + 4
role) so the APIs are not hammered; the cache grows and most postings need none.

`kind` on the page: "stated" (the posting's own figure, from jobbot.salary),
"typical", "web", "role". Never shown as a fact - always "~".
"""
from __future__ import annotations

import json
import os
import re
import statistics
import time
from datetime import datetime

from jobbot import mnc, salary
from jobbot.config import DEFAULT_OUT_ROOT

CACHE_PATH = os.path.join(DEFAULT_OUT_ROOT, "salary_cache.json")
CACHE_DAYS = 60
LAKH = 100_000
TRUSTED = ("ambitionbox.com", "glassdoor", "levels.fyi", "payscale.com", "6figr.com", "indeed.com", "naukri.com", "salary.com")
HIGH_PAY_LPA = 10.0            # "pays well" for this search

_ROLE_FAMILIES = [
    (r"\b(devops|sre|site reliability|platform engineer|cloud engineer|infrastructure)\b", "devops engineer"),
    (r"\b(qa|sdet|test(ing)? engineer|quality)\b", "qa engineer"),
    (r"\b(data engineer|etl|big data)\b", "data engineer"),
    (r"\b(data scientist|machine learning|ml engineer|ai engineer)\b", "machine learning engineer"),
    (r"\b(android|ios|mobile|flutter|react native)\b", "mobile developer"),
    (r"\b(front ?end|frontend|react|angular|ui developer|web developer)\b", "frontend developer"),
    (r"\b(full ?stack)\b", "full stack developer"),
    (r"\b(back ?end|backend|java developer|python developer|node|\.net|api developer)\b", "backend developer"),
    (r"\b(sde|software development engineer|software engineer|swe|software developer|programmer|member of technical staff|developer|engineer)\b",
     "software engineer"),
]
_cache: dict | None = None
_budget = {"web": None, "role": None}


class Unavailable(Exception):
    """The source could not be asked (no budget, no network, rate limited) - unlike "it had
    nothing", this is never cached: the next lookup asks again."""


# ----------------------------------------------------------------------------- helpers

def role_family(title: str) -> str:
    t = (title or "").lower()
    for rx, fam in _ROLE_FAMILIES:
        if re.search(rx, t):
            return fam
    return "software engineer"


def _load_env() -> None:
    """The keys live in the repo's .env (job_bot loads it; a Naukri-side caller may not have)."""
    if os.environ.get("FIRECRAWL_API_KEY") or os.environ.get("RAPIDAPI_KEY"):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "..", "..", ".env"), os.path.join(here, "..", "..", ".env")):
        try:
            with open(cand, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        except OSError:
            continue


_cache_mtime = 0.0


def _read_disk() -> dict:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_load() -> dict:
    """The shared cache, re-read when another process (live feed, Premium, a scan, the hourly
    round all use it) has written it since this one last looked."""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(CACHE_PATH)
    except OSError:
        mtime = 0.0
    if _cache is None or mtime > _cache_mtime:
        disk = _read_disk()
        if _cache:
            disk = _merge(disk, _cache)
        _cache, _cache_mtime = disk, mtime
    return _cache


def _merge(a: dict, b: dict) -> dict:
    """Both caches' entries; for a key in both, the newer one."""
    out = dict(a)
    for k, v in b.items():
        if k not in out or (v.get("at") or 0) >= (out[k].get("at") or 0):
            out[k] = v
    return out


def _cache_save() -> None:
    """Merge with what is on disk now, then write - several processes share this file, and a
    plain write of this process's copy wiped what the others had added (2026-10-12)."""
    global _cache, _cache_mtime
    if _cache is None:
        return
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    merged = _merge(_read_disk(), _cache)
    tmp = f"{CACHE_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    for _attempt in range(5):
        try:
            os.replace(tmp, CACHE_PATH)
            break
        except PermissionError:                 # Windows: another process is replacing it this instant
            time.sleep(0.2)
    _cache = merged
    try:
        _cache_mtime = os.path.getmtime(CACHE_PATH)
    except OSError:
        pass


_budget_window = {"start": 0.0}


def _budget_left(kind: str) -> bool:
    """Lookups allowed per hour (not per process: the live feed runs all day, and a per-process
    budget was spent in its first minutes, after which nothing was ever looked up again)."""
    now = time.time()
    if now - _budget_window["start"] >= 3600:
        _budget_window["start"] = now
        _budget["web"] = _budget["role"] = None
    if _budget[kind] is None:
        default = {"web": 15, "role": 6}[kind]
        raw = os.environ.get("SALARY_LOOKUPS_PER_RUN", "")
        _budget[kind] = int(raw) if raw.isdigit() and kind == "web" else default
    return _budget[kind] > 0


def _spend(kind: str) -> None:
    _budget[kind] = max(0, (_budget[kind] or 0) - 1)


def _key(company: str, title: str, country: str) -> str:
    return f"{mnc.norm(company)}|{role_family(title)}|{(country or 'IN').upper()}"


# ----------------------------------------------------------------------------- sources

def _typical(company: str) -> dict | None:
    e = mnc.match(company)
    if not e or e["lo"] is None:
        return None
    lo, hi = e["lo"], e["hi"] if e["hi"] is not None else e["lo"]
    return {"lpa": round((lo + hi) / 2, 1), "lo": lo, "hi": hi, "kind": "typical",
            "source": f"typical for {e['name']} ({mnc.TIERS.get(e['tier'], e['tier'])}, 0-2 yrs)", "url": e.get("url") or ""}


def _web(company: str, title: str, country: str, http=None) -> dict | None:
    """Firecrawl search: pay figures in the snippets about this company and role (India)."""
    if not company:
        return None
    fam = role_family(title)
    q = f"{company} {fam} salary India LPA fresher 1 year"
    cname = mnc.norm(company).split()[0] if mnc.norm(company) else company.lower()
    return _web_figures(q, must_contain=cname)


# A figure next to these words is the top of the market, not what a 0-2-year hire gets.
_NOT_TYPICAL = re.compile(r"(?i)highest|top\s*\d+\s*%|top\s+(?:earners|paying)|maximum|\bmax\b|\bup to\b|senior|lead\b|"
                          r"\d+\+?\s*(?:years|yrs)\s+of|experienced|10\+|5\+|8\+")
# An AmbitionBox / Glassdoor page about ONE company - not a market figure for the role.
_COMPANY_PAGE = re.compile(r"ambitionbox\.com/salaries/[^/]+-salaries/|glassdoor\.[a-z.]+/Salary/[^/]+-Salaries|levels\.fyi/companies/", re.I)


def _web_figures(q: str, must_contain: str = "", min_trusted: int = 1, role_level: bool = False) -> dict | None:
    """Run one Firecrawl search and read the pay figures (lakhs a year) in its snippets.

    A range counts once, at its midpoint; figures next to "highest / top 10% / senior / N+ years"
    are skipped; with `role_level`, pages about a single company are skipped too."""
    _load_env()
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key or not _budget_left("web"):
        raise Unavailable("web budget")
    import requests
    _spend("web")
    data = None
    for _attempt in range(2):
        try:
            r = requests.post("https://api.firecrawl.dev/v1/search", json={"query": q, "limit": 6},
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=25)
        except Exception as exc:  # noqa: BLE001 - no network: not an answer, never cached
            raise Unavailable(f"web search: {exc}") from exc
        if r.status_code == 429:
            # the plan allows ~18 searches a minute across every process on this PC
            try:
                wait = float((r.json() or {}).get("retry_after_seconds") or 3)
            except ValueError:
                wait = 3.0
            time.sleep(min(10.0, wait + 0.5))
            continue
        if r.status_code != 200:
            raise Unavailable(f"web search: HTTP {r.status_code}")
        try:
            data = r.json().get("data") or []
        except ValueError as exc:
            raise Unavailable("web search: bad JSON") from exc
        break
    if data is None:
        raise Unavailable("web search: rate limited")
    cname = must_contain
    figures, urls = [], []
    for it in data:
        text = f"{it.get('title') or ''}. {it.get('description') or ''}"
        if cname and cname not in text.lower():
            continue
        url = it.get("url") or ""
        if role_level and _COMPANY_PAGE.search(url):
            continue
        trusted = any(d in url for d in TRUSTED)
        # every money phrase in the snippet, as lakhs a year (jobbot.salary reads LPA, ₹, "x lakhs", per month ...)
        seen_here = set()
        for m in re.finditer(r"(?i)(?:₹|rs\.?|inr|lpa|lakh|lacs?|ctc|salary|package)", text):
            window = text[max(0, m.start() - 30): m.end() + 60]
            if _NOT_TYPICAL.search(text[max(0, m.start() - 45): m.start() + 10]):
                continue
            s = salary.parse(window)
            if s is None or not s.min_inr:
                continue
            v = (s.min_inr + s.max_inr) / 2 if s.max_inr else s.min_inr
            if not (2 * LAKH <= v <= 150 * LAKH) or round(v) in seen_here:
                continue
            seen_here.add(round(v))
            figures.append((v / LAKH, trusted))
            if trusted and url not in urls:
                urls.append(url)
    if not figures:
        return None
    pool = [v for v, t in figures if t] or [v for v, _t in figures]
    if len(pool) < 2 and not any(t for _v, t in figures):
        return None
    if sum(1 for _v, t in figures if t) < min_trusted:
        return None
    med = statistics.median(pool)
    return {"lpa": round(med, 1), "lo": round(min(pool), 1), "hi": round(max(pool), 1), "kind": "web",
            "source": "web: " + (re.sub(r"^https?://(www\.)?", "", urls[0]).split("/")[0] if urls else "search snippets"),
            "url": urls[0] if urls else ""}


_PLACE_COUNTRY = {  # cities / areas LinkedIn writes instead of a country
    "amsterdam": "Netherlands", "rotterdam": "Netherlands", "eindhoven": "Netherlands", "utrecht": "Netherlands", "the hague": "Netherlands",
    "london": "United Kingdom", "manchester": "United Kingdom", "edinburgh": "United Kingdom", "england": "United Kingdom", "uk": "United Kingdom",
    "dublin": "Ireland", "berlin": "Germany", "munich": "Germany", "münchen": "Germany", "hamburg": "Germany", "frankfurt": "Germany",
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates", "uae": "United Arab Emirates", "paris": "France",
    "madrid": "Spain", "barcelona": "Spain", "lisbon": "Portugal", "zurich": "Switzerland", "stockholm": "Sweden", "helsinki": "Finland",
    "tokyo": "Japan", "sydney": "Australia", "melbourne": "Australia", "toronto": "Canada", "vancouver": "Canada", "bangkok": "Thailand",
    "kuala lumpur": "Malaysia", "new york": "United States", "san francisco": "United States", "seattle": "United States", "usa": "United States",
}


def _country_name(country: str) -> str:
    """A country name from a code ("DE"), a name, or a LinkedIn place ("Germany (Remote)", "Amsterdam Area (Hybrid)")."""
    c = re.sub(r"\(.*?\)", " ", country or "IN")
    c = re.sub(r"\b(area|region|metropolitan|greater|district|remote|hybrid|on-?site)\b", " ", c, flags=re.I)
    c = re.sub(r"\s+", " ", c).strip(" ,-") or "IN"
    if len(c) == 2:
        try:
            from jobbot.config import COUNTRIES
            return (COUNTRIES.get(c.upper()) or {}).get("name") or c
        except Exception:  # noqa: BLE001
            return c
    low = c.lower()
    if low in _LOCAL_CURRENCY:
        return c.title() if low != "united arab emirates" else "United Arab Emirates"
    for place, name in _PLACE_COUNTRY.items():
        if re.search(r"\b" + re.escape(place) + r"\b", low):
            return name
    return c


_PERIOD = {"YEAR": 1, "ANNUAL": 1, "MONTH": 12, "WEEK": 52, "DAY": 260, "HOUR": 2080}
_LOCAL_CURRENCY = {"india": "INR", "united arab emirates": "AED", "singapore": "SGD", "united kingdom": "GBP", "germany": "EUR",
                   "netherlands": "EUR", "ireland": "EUR", "france": "EUR", "spain": "EUR", "finland": "EUR", "portugal": "EUR",
                   "japan": "JPY", "australia": "AUD", "canada": "CAD", "switzerland": "CHF", "sweden": "SEK", "thailand": "THB",
                   "malaysia": "MYR", "united states": "USD", "usa": "USD"}


def _role(title: str, country: str) -> dict | None:
    """The market figure for the role family in the country, for a company nothing specific is
    known about - cached per role family + country (one lookup serves every such company).

    India: a role-level web search (AmbitionBox / Glassdoor India snippets). JSearch's "India"
    estimate is US Glassdoor data in dollars (2026-10-12: $107k for a software engineer), so it is
    not used here. Elsewhere: JSearch, with its period honoured (AED per MONTH x 12) and rows in a
    currency that is not the country's own thrown away."""
    cache = _cache_load()
    cname = _country_name(country)
    rk = f"role|{role_family(title)}|{cname.lower()}"
    hit = cache.get(rk)
    if hit and hit.get("at") and time.time() - hit["at"] < CACHE_DAYS * 86400 and hit.get("est"):
        return hit["est"]
    if cname.lower() == "india":
        try:
            est = _web_figures(f"{role_family(title)} salary India fresher 0-2 years LPA ambitionbox", min_trusted=1, role_level=True)
        except Unavailable:
            return None                              # rate limited / offline: asked again next time
        if est:
            est.update(kind="role", source=f"market median for a {role_family(title)} in India, 0-2 yrs ({est['source']})")
            cache[rk] = {"at": time.time(), "est": est}
            _cache_save()
        return est
    _load_env()
    key = os.environ.get("RAPIDAPI_KEY")
    if not key or not _budget_left("role"):
        return None
    import requests
    _spend("role")
    try:
        r = requests.get("https://jsearch.p.rapidapi.com/estimated-salary", timeout=20,
                         params={"job_title": role_family(title), "location": _country_name(country),
                                 "location_type": "ANY", "years_of_experience": "ONE_TO_THREE"},
                         headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
        if r.status_code != 200:
            return None
        rows = (r.json() or {}).get("data") or []
    except Exception:  # noqa: BLE001
        return None
    meds = []
    want_cur = _LOCAL_CURRENCY.get(cname.lower())
    if not want_cur:
        return None              # not a country we can check the currency of ("EMEA", "Worldwide"): no figure beats a wrong one
    for row in rows:
        cur = (row.get("salary_currency") or "").upper()
        med = row.get("median_base_salary") or row.get("median_salary")
        per = _PERIOD.get((row.get("salary_period") or "YEAR").upper())
        if not med or not cur or not per or (want_cur and cur != want_cur):
            continue                                   # another country's data, or a period we cannot read
        s = salary.parse(f"{cur} {round(float(med) * per)} per year")
        if s and s.min_inr and 1 * LAKH <= s.min_inr <= 300 * LAKH:
            meds.append(s.min_inr / LAKH)
    if not meds:
        return None
    med = statistics.median(meds)
    est = {"lpa": round(med, 1), "lo": round(min(meds), 1), "hi": round(max(meds), 1), "kind": "role",
           "source": f"market median for a {role_family(title)} in {cname} (JSearch / Glassdoor, base pay)", "url": ""}
    cache[rk] = {"at": time.time(), "est": est}
    _cache_save()
    return est


# ----------------------------------------------------------------------------- the one call

NONE_RETRY_DAYS = 3        # a company nothing was found for is asked again after this


def estimate(title: str, company: str, country: str = "IN", allow_web: bool = True) -> dict | None:
    """The best available estimate for this posting, from the cache or the sources above.

    Company-specific answers (typical band, web search) are cached per company + role + country;
    the role-level estimate is the fallback for any company and is cached per role + country.
    A lookup skipped because the hour's budget was spent is NOT cached - the next run asks again."""
    cache = _cache_load()
    k = _key(company, title, country)
    hit = cache.get(k)
    if hit and hit.get("at"):
        age = time.time() - hit["at"]
        if hit.get("est") and age < CACHE_DAYS * 86400:
            return hit["est"]
        if not hit.get("est") and age < NONE_RETRY_DAYS * 86400:
            return _role(title, country)                     # known to have no company figure: the role one
    india = _country_name(country).lower() == "india"
    est = _typical(company) if india else None        # the bands in mnc.txt are India figures: TCS Amsterdam is not 5 LPA
    tried_web = False
    if est is None and allow_web and _budget_left("web"):
        try:
            est = _web(company, title, country)
            tried_web = True                                  # the search answered (with or without figures)
        except Unavailable:
            est = None                                        # rate limited / offline: not cached, asked again
    if est is not None or tried_web:
        cache[k] = {"at": time.time(), "est": est}           # a real answer, or a real "nothing found"
        _cache_save()
    return est or _role(title, country)


def lpa_of(stated_lpa: float | None, est: dict | None) -> tuple[float | None, str]:
    """(lakhs a year, kind) - the posting's own figure first."""
    if stated_lpa:
        return float(stated_lpa), "stated"
    if est and est.get("lpa"):
        return float(est["lpa"]), est.get("kind") or "est"
    return None, ""


def label(lpa: float | None, kind: str) -> str:
    if not lpa:
        return ""
    fig = ("%.1f" % lpa).rstrip("0").rstrip(".")
    return f"₹{fig} LPA" if kind == "stated" else f"~₹{fig} LPA"


# ----------------------------------------------------------------------------- job-hunt Job objects

def annotate_jobs(jobs, log=None, country_of=lambda j: getattr(j, "country", "") or "IN") -> dict:
    """extra.lpa / lpa_kind / lpa_source / lpa_url / is_mnc / mnc_tier / mnc_name on every job,
    and a few score points for pay and employer (see score_bonus). Lookups go to the best-scored
    jobs first while the run's budget lasts; the rest get the free sources only."""
    ordered = sorted(jobs, key=lambda j: -(getattr(j, "score", None) or 0))
    n_est = n_mnc = 0
    for j in ordered:
        extra = getattr(j, "extra", None)
        if extra is None:
            j.extra = extra = {}
        m = mnc.match(getattr(j, "company", "") or "")
        extra["is_mnc"] = bool(m)
        if m:
            extra["mnc_tier"], extra["mnc_name"] = m["tier"], m["name"]
            n_mnc += 1
        stated = extra.get("salary_lpa") if extra.get("salary_stated") else None
        if stated:
            extra["lpa"], extra["lpa_kind"], extra["lpa_source"] = float(stated), "stated", "the posting"
        else:
            est = estimate(getattr(j, "title", "") or "", getattr(j, "company", "") or "", country_of(j),
                           allow_web=(getattr(j, "country", "IN") in ("IN", "", None)))
            if est:
                extra["lpa"], extra["lpa_kind"], extra["lpa_source"], extra["lpa_url"] = est["lpa"], est["kind"], est["source"], est.get("url", "")
                extra["lpa_lo"], extra["lpa_hi"] = est.get("lo"), est.get("hi")
                n_est += 1
        b = score_bonus(extra)
        if b and getattr(j, "score", None) is not None:
            extra["pay_bonus"] = b
            j.score = round(max(0.0, min(100.0, j.score + b)), 1)
    if log:
        log(f"pay & employer: {n_mnc} MNC posting(s), pay known or estimated for {n_est + sum(1 for j in jobs if (j.extra or {}).get('lpa_kind') == 'stated')} of {len(jobs)}")
    return {"mnc": n_mnc, "estimated": n_est}


def score_bonus(extra: dict) -> float:
    """A few points for what you are after: a well-paying MNC / unicorn / big-tech posting.
    + up to 8 for the employer, + up to 8 for pay at or above 10 LPA, - for pay stated under 6 LPA."""
    b = 0.0
    tier = extra.get("mnc_tier") or ""
    if extra.get("is_mnc"):
        b += {"bigtech": 8, "hft": 8, "unicorn": 7, "product": 6, "finance": 6, "gcc": 4, "consulting": 3, "itservices": 1}.get(tier, 4)
    lpa, kind = extra.get("lpa"), extra.get("lpa_kind")
    if lpa:
        if lpa >= 20:
            b += 8 if kind == "stated" else 5
        elif lpa >= HIGH_PAY_LPA:
            b += 6 if kind == "stated" else 3
        elif kind == "stated" and lpa < 6:
            b -= 10
        elif kind == "typical" and lpa < 6:
            b -= 4
    return round(b, 1)
