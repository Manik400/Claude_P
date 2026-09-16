"""Who to talk to at each company: recruiters, hiring managers, engineering leads.

A report with a name and an email beats one with only an Apply button, so
after a search the top companies are enriched, from whatever is available:

    the postings themselves   emails in the description, the LinkedIn job
                              poster (Apify LinkedIn source), the company site
    SignalHire   SIGNALHIRE_API_KEY  people at the company by title (recruiters,
                 engineering managers, heads of engineering, CTO) - names, titles,
                 location. Contact reveal is a credit per person and asynchronous,
                 so the report links each person to LinkedIn / SignalHire instead.
    Hunter.io    HUNTER_API_KEY      the company's email pattern and named
                 emails with positions (domain search; 25 free / month)
    Apollo.io    APOLLO_API_KEY      people search by company + title - names,
                 titles, LinkedIn URLs (free tier)

None of the keys is required. Without any, the result still carries the
postings' own emails, the poster, and ready-made LinkedIn / Google people
searches per role. Output shape, one entry per company:

    {"company": ..., "domain": ..., "site": ..., "emails": [...],
     "people": [{"name", "title", "email", "linkedin", "location", "source", "confidence"}],
     "searches": {"Tech recruiters": {"linkedin": url, "google": url}, ...}}
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote, urlparse

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
NOISE_DOMAINS = ("example.com", "linkedin.com", "indeed.com", "naukri.com", "greenhouse.io", "lever.co",
                 "workday.com", "smartrecruiters.com", "gmail.com", "yahoo.com", "hotmail.com", "sentry.io")
TITLES = ["Technical Recruiter", "Talent Acquisition", "Engineering Manager", "Head of Engineering",
          "VP Engineering", "CTO"]
SEARCH_GROUPS = [
    ("Tech recruiters", '"Technical Recruiter" OR "Talent Acquisition" OR "Recruiter"'),
    ("Engineering managers", '"Engineering Manager" OR "Team Lead"'),
    ("Head of Engineering / CTO", '"Head of Engineering" OR "VP Engineering" OR "CTO"'),
]
MAX_COMPANIES = int(os.environ.get("CONTACTS_MAX_COMPANIES", "30"))
PEOPLE_PER_COMPANY = 8


def providers() -> list[str]:
    out = []
    for key, name in (("SIGNALHIRE_API_KEY", "signalhire"), ("HUNTER_API_KEY", "hunter"), ("APOLLO_API_KEY", "apollo")):
        if os.environ.get(key):
            out.append(name)
    return out


def _domain(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _search_links(company: str, city: str, role: str) -> dict:
    where = f' "{city}"' if city else ""
    out = {}
    for label, q in SEARCH_GROUPS + [(f"Senior {role}", f'"Senior {role}"')]:
        query = f'"{company}" ({q}){where}'
        out[label] = {
            "linkedin": "https://www.linkedin.com/search/results/people/?keywords=" + quote(query),
            "google": "https://www.google.com/search?q=" + quote("site:linkedin.com/in " + query),
        }
    return out


# ----------------------------------------------------------------- providers

def _signalhire(http, company: str, location: str, log) -> list[dict]:
    key = os.environ.get("SIGNALHIRE_API_KEY")
    if not key:
        return []
    people = []
    for title in TITLES:
        if len(people) >= PEOPLE_PER_COMPANY:
            break
        body = {"currentCompany": company, "currentTitle": title, "size": 3}
        if location:
            body["location"] = location
        try:
            r = http.post("https://www.signalhire.com/api/v1/candidate/searchByQuery", json=body,
                          headers={"apikey": key, "Content-Type": "application/json"}, retries=0, timeout=30)
        except Exception as exc:  # noqa: BLE001
            log(f"  signalhire {company}: {exc}")
            return people
        if r.status_code != 200:
            if r.status_code in (401, 402, 429):
                log(f"  signalhire: HTTP {r.status_code} - check the key / credits")
                return people
            continue
        for p in (r.json().get("profiles") or []):
            exp = (p.get("experience") or [{}])[0] if p.get("experience") else {}
            name = p.get("fullName") or ""
            if not name or any(x["name"] == name for x in people):
                continue
            people.append({
                "name": name, "title": exp.get("title") or exp.get("position") or title,
                "company": exp.get("company") or company, "location": p.get("location") or "",
                "email": "", "linkedin": "https://www.linkedin.com/search/results/people/?keywords=" + quote(f'"{name}" "{company}"'),
                "reveal": "https://www.signalhire.com/search?q=" + quote(f"{name} {company}"),
                "source": "signalhire", "confidence": None,
            })
    return people


def _hunter(http, company: str, domain: str, log) -> tuple[list[dict], str, list[str]]:
    key = os.environ.get("HUNTER_API_KEY")
    if not key:
        return [], domain, []
    params = {"api_key": key, "limit": 10, "department": "hr,it,management,executive"}
    if domain:
        params["domain"] = domain
    else:
        params["company"] = company
    try:
        r = http.get("https://api.hunter.io/v2/domain-search", params=params, retries=0, timeout=30)
    except Exception as exc:  # noqa: BLE001
        log(f"  hunter {company}: {exc}")
        return [], domain, []
    if r.status_code != 200:
        if r.status_code in (401, 429):
            log(f"  hunter: HTTP {r.status_code} - check the key / quota")
        return [], domain, []
    data = r.json().get("data") or {}
    people, emails = [], []
    for e in data.get("emails") or []:
        addr = e.get("value") or ""
        if not addr:
            continue
        emails.append(addr)
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        people.append({"name": name or addr, "title": e.get("position") or "", "company": company,
                       "location": "", "email": addr, "linkedin": e.get("linkedin") or "",
                       "source": "hunter", "confidence": e.get("confidence")})
    pattern = data.get("pattern")
    if pattern and data.get("domain"):
        emails.append(f"pattern: {pattern}@{data['domain']}")
    return people, data.get("domain") or domain, emails


def _apollo(http, company: str, log) -> list[dict]:
    key = os.environ.get("APOLLO_API_KEY")
    if not key:
        return []
    body = {"q_organization_name": company, "person_titles": TITLES, "page": 1, "per_page": PEOPLE_PER_COMPANY}
    try:
        r = http.post("https://api.apollo.io/api/v1/mixed_people/search", json=body,
                      headers={"X-Api-Key": key, "Content-Type": "application/json", "Cache-Control": "no-cache"},
                      retries=0, timeout=30)
    except Exception as exc:  # noqa: BLE001
        log(f"  apollo {company}: {exc}")
        return []
    if r.status_code != 200:
        if r.status_code in (401, 403, 422, 429):
            log(f"  apollo: HTTP {r.status_code} - check the key / plan")
        return []
    people = []
    for p in r.json().get("people") or []:
        org = (p.get("organization") or {}).get("name") or company
        if company.lower()[:6] not in org.lower():
            continue
        people.append({"name": p.get("name") or "", "title": p.get("title") or "", "company": org,
                       "location": ", ".join(x for x in (p.get("city"), p.get("country")) if x),
                       "email": p.get("email") if p.get("email") and "not_unlocked" not in p.get("email") else "",
                       "linkedin": p.get("linkedin_url") or "", "source": "apollo", "confidence": None})
    return people


# ---------------------------------------------------------------------- main

def enrich(jobs, http, roles, log=print, max_companies: int = MAX_COMPANIES) -> dict:
    """Contacts per company for the best-scoring companies in `jobs` (Job objects or dicts)."""
    def g(j, k, d=None):
        return (j.get(k, d) if isinstance(j, dict) else getattr(j, k, d))

    by_company: dict[str, list] = {}
    for j in jobs:
        name = (g(j, "company") or "").strip()
        if name:
            by_company.setdefault(name, []).append(j)
    ranked = sorted(by_company.items(), key=lambda kv: -max((g(j, "score") or 0) for j in kv[1]))
    role = (roles or ["software engineer"])[0]
    active = providers()
    log(f"contacts: {min(len(ranked), max_companies)} of {len(ranked)} companies, providers: {', '.join(active) or 'none (links + what the postings say)'}")
    out = {}
    for company, cjobs in ranked[:max_companies]:
        emails, people, site = [], [], ""
        for j in cjobs:
            extra = g(j, "extra") or {}
            text = " ".join(str(g(j, k) or "") for k in ("snippet", "description"))
            for m in EMAIL.findall(text):
                if not any(m.lower().endswith(d) for d in NOISE_DOMAINS) and m not in emails:
                    emails.append(m)
            if extra.get("poster") and extra["poster"].get("name"):
                p = extra["poster"]
                if not any(x["name"] == p["name"] for x in people):
                    people.append({"name": p["name"], "title": p.get("title") or "posted this job", "company": company,
                                   "location": "", "email": "", "linkedin": p.get("url") or "",
                                   "source": "posting", "confidence": None})
            site = site or extra.get("company_site") or ""
        domain = _domain(site) if site else ""
        if not domain:
            for e in emails:
                d = e.split("@")[-1].lower()
                if not any(d.endswith(n) for n in NOISE_DOMAINS):
                    domain = d
                    break
        loc = next((g(j, "location") or "" for j in cjobs if g(j, "location")), "")
        city = loc.split(",")[0].strip() if loc else ""
        if active:
            people += _signalhire(http, company, city, log)
            h_people, domain, h_emails = _hunter(http, company, domain, log)
            people += h_people
            emails += [e for e in h_emails if e not in emails]
            people += _apollo(http, company, log)
        seen, uniq = set(), []
        for p in people:
            k = (p["name"].lower(), p.get("email", "").lower())
            if k in seen:
                continue
            seen.add(k)
            uniq.append(p)
        out[company] = {"company": company, "domain": domain, "site": site, "emails": emails[:10],
                        "people": uniq[:PEOPLE_PER_COMPANY * 2], "searches": _search_links(company, city, role),
                        "jobs": len(cjobs), "best_score": max((g(j, "score") or 0) for j in cjobs)}
    found = sum(1 for c in out.values() if c["people"] or c["emails"])
    log(f"contacts: names or emails for {found} of {len(out)} companies")
    return out


def attach(jobs, contacts: dict) -> int:
    """Put each company's contacts on its jobs (extra.contacts) so the phone shows them per posting."""
    n = 0
    for j in jobs:
        name = (j.get("company") if isinstance(j, dict) else getattr(j, "company", "")) or ""
        c = contacts.get(name.strip())
        if not c:
            continue
        extra = j.get("extra") if isinstance(j, dict) else getattr(j, "extra", None)
        if extra is None:
            extra = {}
            if isinstance(j, dict):
                j["extra"] = extra
            else:
                j.extra = extra
        extra["contacts"] = {k: v for k, v in c.items() if k in ("domain", "site", "emails", "people", "searches")}
        n += 1
    return n
