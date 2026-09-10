"""Platforms that block scripts (Indeed, Glassdoor, Naukri, StepStone, ...).

Three things are provided for them:
  * direct_links()      one-click search URLs per country for the report header
  * fallback_queries()  a web-search plan (site: queries) that Claude or Firecrawl can execute
  * merge_extra()       merge jobs found that way (a JSON list) into an existing run
"""
import json
import os
import re
from urllib.parse import quote_plus

from .config import COUNTRIES, REMOTE, resolve_country
from .experience import annotate, linkedin_experience_codes
from .models import Job
from .textutil import slugify

EU = ["DE", "NL", "ES", "FI", "GB", "IE", "FR", "SE", "NO", "DK", "CH", "AT", "PT", "IT", "PL", "BE"]


def _q(s):
    return quote_plus(s)


# name, countries (None = all), url builder(role, cc, meta), web-search site (None = not searchable), url hint for job pages
PLATFORMS = [
    dict(key="indeed", name="Indeed", countries=None,
         url=lambda r, cc, m: f"https://{m['indeed']}/jobs?q={_q(r)}&fromage=30&sort=date",
         site=lambda cc, m: m["indeed"], hint="viewjob"),
    dict(key="glassdoor", name="Glassdoor", countries=None,
         url=lambda r, cc, m: f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={_q(r)}&locT=N&locKeyword={_q(m['name'])}",
         site=lambda cc, m: "glassdoor.com", hint="job-listing"),
    dict(key="naukri", name="Naukri", countries=None,
         url=lambda r, cc, m: f"https://www.naukri.com/{slugify(r)}-jobs-in-{slugify(m['name'])}",
         site=lambda cc, m: "naukri.com", hint="job-listings"),
    dict(key="stepstone", name="StepStone", countries=["DE", "AT"],
         url=lambda r, cc, m: f"https://www.stepstone.{'at' if cc == 'AT' else 'de'}/jobs/{slugify(r)}?sort=2",
         site=lambda cc, m: f"stepstone.{'at' if cc == 'AT' else 'de'}", hint="stellenangebote"),
    dict(key="hirist", name="Hirist", countries=["IN"],
         url=lambda r, cc, m: f"https://www.hirist.tech/search/{_q(r)}",
         site=lambda cc, m: "hirist.tech", hint="/j/"),
    dict(key="jobly", name="Jobly", countries=["FI"],
         url=lambda r, cc, m: f"https://www.jobly.fi/tyopaikat?search={_q(r)}",
         site=lambda cc, m: "jobly.fi", hint="tyopaikka"),
    dict(key="oikotie", name="Oikotie Työpaikat", countries=["FI"],
         url=lambda r, cc, m: f"https://tyopaikat.oikotie.fi/tyopaikat?hakusana={_q(r)}",
         site=lambda cc, m: "tyopaikat.oikotie.fi", hint="tyopaikat/"),
    dict(key="nvb", name="Nationale Vacaturebank", countries=["NL"],
         url=lambda r, cc, m: f"https://www.nationalevacaturebank.nl/vacature/zoeken?query={_q(r)}",
         site=lambda cc, m: "nationalevacaturebank.nl", hint="/vacature/"),
    dict(key="iamexpat", name="IamExpat Jobs", countries=["NL", "DE"],
         url=lambda r, cc, m: (f"https://www.iamexpat.nl/career/jobs-netherlands?keywords={_q(r)}" if cc == "NL"
                               else f"https://www.iamexpat.de/career/jobs-germany?keywords={_q(r)}"),
         site=lambda cc, m: "iamexpat.nl" if cc == "NL" else "iamexpat.de", hint="/career/jobs"),
    dict(key="careercross", name="CareerCross", countries=["JP"],
         url=lambda r, cc, m: f"https://www.careercross.com/en/job-search?keyword={_q(r)}",
         site=lambda cc, m: "careercross.com", hint="/en/job/"),
    dict(key="gaijinpot", name="GaijinPot Jobs", countries=["JP"],
         url=lambda r, cc, m: f"https://jobs.gaijinpot.com/index/index/search?keyword={_q(r)}",
         site=lambda cc, m: "jobs.gaijinpot.com", hint="/job/"),
    dict(key="jora", name="Jora", countries=["AU", "NZ"],
         url=lambda r, cc, m: f"https://{'nz' if cc == 'NZ' else 'au'}.jora.com/j?q={_q(r)}&l={_q(m['name'])}",
         site=lambda cc, m: f"{'nz' if cc == 'NZ' else 'au'}.jora.com", hint="/job/"),
    dict(key="jobtopgun", name="JobTopGun", countries=["TH"],
         url=lambda r, cc, m: f"https://www.jobtopgun.com/en/search?keyword={_q(r)}",
         site=lambda cc, m: "jobtopgun.com", hint="/en/job"),
    dict(key="arbeitsagentur", name="Arbeitsagentur Jobsuche", countries=["DE"],
         url=lambda r, cc, m: f"https://www.arbeitsagentur.de/jobsuche/suche?was={_q(r)}&angebotsart=1",
         site=None, hint=""),
    dict(key="eures", name="EURES (EU portal)", countries=EU,
         url=lambda r, cc, m: (f"https://europa.eu/eures/portal/jv-se/search?page=1&resultsPerPage=10&orderBy=BEST_MATCH"
                               f"&keywordsEverywhere={_q(r)}&locationCodes={cc.lower()}&lang=en"),
         site=None, hint=""),
    dict(key="linkedin_web", name="LinkedIn (full search)", countries=None,
         url=lambda r, cc, m: f"https://www.linkedin.com/jobs/search/?keywords={_q(r)}&location={_q(m['linkedin'])}&f_TPR=r2592000",
         site=None, hint=""),
    dict(key="wellfound_web", name="Wellfound", countries=None,
         url=lambda r, cc, m: f"https://wellfound.com/role/l/{slugify(r) or 'software-engineer'}/{m['wellfound']}",
         site=None, hint=""),
]

# platforms we already scrape directly; their site: queries are skipped in the web-search plan
DIRECT_KEYS = {"linkedin_web", "wellfound_web", "arbeitsagentur", "eures"}


def direct_links(role, country):
    """[{name, url}] for one country - shown in the report header so blocked platforms are one click away."""
    if country == REMOTE:
        return [
            {"name": "Remotive", "url": f"https://remotive.com/remote-jobs?search={_q(role)}"},
            {"name": "RemoteOK", "url": f"https://remoteok.com/remote-{slugify(role)}-jobs"},
            {"name": "We Work Remotely", "url": f"https://weworkremotely.com/remote-jobs/search?term={_q(role)}"},
            {"name": "LinkedIn remote", "url": f"https://www.linkedin.com/jobs/search/?keywords={_q(role)}&f_WT=2&f_TPR=r2592000"},
        ]
    meta = COUNTRIES.get(country)
    if not meta:
        return []
    out = []
    for p in PLATFORMS:
        if p["countries"] is not None and country not in p["countries"]:
            continue
        try:
            out.append({"name": p["name"], "url": p["url"](role, country, meta)})
        except Exception:
            continue
    return out


def fallback_queries(roles, countries, user_years=None):
    """Web-search plan for platforms we cannot fetch directly."""
    plan = []
    for cc in countries:
        if cc == REMOTE:
            continue
        meta = COUNTRIES.get(cc)
        if not meta:
            continue
        for p in PLATFORMS:
            if p["key"] in DIRECT_KEYS or not p["site"]:
                continue
            if p["countries"] is not None and cc not in p["countries"]:
                continue
            site = p["site"](cc, meta)
            for role in roles:
                country_part = "" if site.startswith(("de.", "nl.", "es.", "fi.", "au.", "jp.", "th.", "in.", "sg.")) or site.count(".") >= 2 and site.split(".")[0] in ("de", "nl", "es", "fi", "au", "jp", "th") else f" {meta['name']}"
                plan.append({
                    "platform": p["key"], "platform_name": p["name"], "country": cc, "country_name": meta["name"],
                    "query": f'site:{site} "{role}"{country_part}',
                    "url_must_contain": p["hint"],
                    "role": role,
                })
    return plan


def merge_extra(jobs, extra_items, user_years=None):
    """Merge a list of dicts (title, company, url, country, location, source, source_name, snippet, posted, salary)."""
    existing_urls = {j.dedup_url() for j in jobs}
    existing_keys = {j.dedup_key() for j in jobs}
    added = 0
    for it in extra_items:
        if not isinstance(it, dict) or not it.get("url") or not it.get("title"):
            continue
        cc = it.get("country") or ""
        code = cc if cc in COUNTRIES or cc == REMOTE else resolve_country(cc)
        if not code:
            continue
        src = (it.get("source") or "web").lower().replace(" ", "")
        j = Job(
            source=src,
            source_name=it.get("source_name") or it.get("source") or "Web search",
            title=it.get("title", ""),
            company=it.get("company", ""),
            url=it.get("url", ""),
            country=code,
            location=it.get("location", "") or COUNTRIES.get(code, {}).get("name", ""),
            posted=it.get("posted"),
            salary=it.get("salary", "") or "",
            snippet=it.get("snippet", "") or "",
            description=it.get("description", "") or "",
            remote=it.get("remote"),
            query=it.get("query", "") or "",
        ).finalize()
        if j.dedup_url() in existing_urls or j.dedup_key() in existing_keys:
            continue
        annotate(j, user_years)
        j.extra["from_fallback"] = True
        jobs.append(j)
        existing_urls.add(j.dedup_url())
        existing_keys.add(j.dedup_key())
        added += 1
    return added


def load_extra_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("jobs") or data.get("items") or []
    return data
