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


def _cache_load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _cache_save() -> None:
    if _cache is None:
        return
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)


def _budget_left(kind: str) -> bool:
    if _budget[kind] is None:
        default = {"web": 12, "role": 4}[kind]
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
    """Firecrawl search: pay figures in the snippets about this company and role."""
    _load_env()
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key or not company or not _budget_left("web"):
        return None
    import requests
    fam = role_family(title)
    where = "India LPA" if (country or "IN").upper() == "IN" else country
    q = f"{company} {fam} salary {where} fresher 1 year"
    _spend("web")
    try:
        r = requests.post("https://api.firecrawl.dev/v1/search", json={"query": q, "limit": 6},
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=25)
        if r.status_code != 200:
            return None
        data = r.json().get("data") or []
    except Exception:  # noqa: BLE001 - no network, odd JSON: just no estimate
        return None
    cname = mnc.norm(company).split()[0] if mnc.norm(company) else company.lower()
    figures, urls = [], []
    for it in data:
        text = f"{it.get('title') or ''}. {it.get('description') or ''}"
        if cname and cname not in text.lower():
            continue
        url = it.get("url") or ""
        trusted = any(d in url for d in TRUSTED)
        # every money phrase in the snippet, as lakhs a year (jobbot.salary reads LPA, ₹, "x lakhs", per month ...)
        for m in re.finditer(r"(?i)(?:₹|rs\.?|inr|lpa|lakh|lacs?|ctc|salary|package)", text):
            s = salary.parse(text[max(0, m.start() - 30): m.end() + 60])
            if s is None:
                continue
            for v in (s.min_inr, s.max_inr):
                if v and 2 * LAKH <= v <= 150 * LAKH:
                    figures.append((v / LAKH, trusted))
            if trusted and url not in urls:
                urls.append(url)
    if not figures:
        return None
    pool = [v for v, t in figures if t] or [v for v, _t in figures]
    if len(pool) < 2 and not any(t for _v, t in figures):
        return None
    med = statistics.median(pool)
    return {"lpa": round(med, 1), "lo": round(min(pool), 1), "hi": round(max(pool), 1), "kind": "web",
            "source": "web: " + (re.sub(r"^https?://(www\.)?", "", urls[0]).split("/")[0] if urls else "search snippets"),
            "url": urls[0] if urls else ""}


def _role(title: str, country: str) -> dict | None:
    """JSearch estimated salary for the role in the country - not company-specific."""
    _load_env()
    key = os.environ.get("RAPIDAPI_KEY")
    if not key or not _budget_left("role"):
        return None
    import requests
    _spend("role")
    try:
        r = requests.get("https://jsearch.p.rapidapi.com/estimated-salary", timeout=20,
                         params={"job_title": role_family(title), "location": "India" if (country or "IN").upper() == "IN" else country,
                                 "location_type": "ANY", "years_of_experience": "ONE_TO_THREE"},
                         headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
        if r.status_code != 200:
            return None
        rows = (r.json() or {}).get("data") or []
    except Exception:  # noqa: BLE001
        return None
    meds = []
    for row in rows:
        cur = (row.get("salary_currency") or "INR").upper()
        med = row.get("median_salary") or row.get("median_base_salary")
        if not med:
            continue
        s = salary.parse(f"{cur} {med} per year")
        if s and s.min_inr:
            meds.append(s.min_inr / LAKH)
    if not meds:
        return None
    med = statistics.median(meds)
    return {"lpa": round(med, 1), "lo": round(min(meds), 1), "hi": round(max(meds), 1), "kind": "role",
            "source": f"typical for a {role_family(title)} in India (JSearch)", "url": ""}


# ----------------------------------------------------------------------------- the one call

def estimate(title: str, company: str, country: str = "IN", allow_web: bool = True) -> dict | None:
    """The best available estimate for this posting, from the cache or the sources above."""
    cache = _cache_load()
    k = _key(company, title, country)
    hit = cache.get(k)
    if hit and hit.get("at") and time.time() - hit["at"] < CACHE_DAYS * 86400 and (hit.get("est") or not allow_web):
        return hit.get("est")
    est = _typical(company)
    if est is None and allow_web:
        est = _web(company, title, country)
    if est is None and allow_web:
        est = _role(title, country)
    cache[k] = {"at": time.time(), "est": est}
    _cache_save()
    return est


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
