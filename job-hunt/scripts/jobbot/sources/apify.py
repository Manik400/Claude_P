"""Apify actors (optional, APIFY_TOKEN) - real scrapers for the boards that block scripts.

Naukri, Indeed and LinkedIn either sign their APIs or block datacenter IPs, so
the built-in sources cover them thinly (LinkedIn's guest search) or not at all
(Naukri, Indeed - web-search fallback only). With an Apify token the run rents
their scrapers instead, which is what makes an India search worth reading:

    apify-naukri     valig/naukri-jobs-scraper        India only      ~$0.4 per 1000 jobs
    apify-indeed     valig/indeed-jobs-scraper        60+ countries   ~$0.1 per 1000 jobs
    apify-linkedin   curious_coder/linkedin-jobs-scraper  everywhere  ~$2 per 1000 jobs;
                     also returns the job poster (name, title, LinkedIn profile) - a contact

Set APIFY_TOKEN (https://console.apify.com/account/integrations). APIFY_SOURCES
picks which of the three run (default "naukri,indeed"; add "linkedin" to spend
on it). Each actor call is synchronous and capped by --max-per-source.

Spending is paced against the account's real usage (users/me/limits), so the PC's
half-hourly rounds and the GitHub runs share one budget: APIFY_MONTHLY_USD (default 4.5,
under the free plan's $5) spread evenly over the billing cycle. A call that would go past
what the cycle has earned so far is skipped with a log line, and the next day's share
lets it run again. On top of that no day spends more than APIFY_DAILY_USD (default the
monthly budget / 30), counted on this PC (a GitHub runner starts at zero, so there it is
a per-run cap), so a quiet fortnight cannot be spent in one afternoon.
"""
import math
import os
import re
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import COUNTRIES
from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

RUN_SYNC = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
LIMITS = "https://api.apify.com/v2/users/me/limits"
# USD per result on the free tier, plus ~$0.001 per actor start (Apify Store, Sep 2026)
PRICE = {"valig/naukri-jobs-scraper": 0.0004, "valig/indeed-jobs-scraper": 0.0001,
         "curious_coder/linkedin-jobs-scraper": 0.002}
START_USD = 0.001
_budget_lock = threading.Lock()
USAGE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "JobHuntPhone" / "apify_usage.json"


def _today_spent():
    try:
        used = json.loads(USAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        used = {}
    return float(used.get("usd") or 0) if used.get("day") == time.strftime("%Y-%m-%d") else 0.0


def _add_spent(usd):
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    USAGE.write_text(json.dumps({"day": time.strftime("%Y-%m-%d"), "usd": round(_today_spent() + usd, 5)}),
                     encoding="utf-8")
INDEED_COUNTRIES = {"AR", "AU", "AT", "BH", "BE", "BR", "CA", "CL", "CN", "CO", "CR", "CZ", "DK", "EC", "EG", "FI", "FR", "DE",
                    "GR", "HK", "HU", "IN", "ID", "IE", "IL", "IT", "JP", "KW", "LU", "MY", "MX", "MA", "NL", "NZ", "NG", "NO",
                    "OM", "PK", "PA", "PE", "PH", "PL", "PT", "QA", "RO", "SA", "SG", "ZA", "KR", "ES", "SE", "CH", "TW", "TH",
                    "TR", "UA", "AE", "GB", "US", "UY", "VE", "VN"}


def _enabled_sources():
    raw = os.environ.get("APIFY_SOURCES", "naukri,indeed")
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def _allowance(ctx, token):
    """(spent this cycle, what the cycle allows by now) in USD, or None when Apify does not say."""
    try:
        d = ctx.http.get_json(LIMITS, params={"token": token}, retries=1).get("data") or {}
        spent = float((d.get("current") or {}).get("monthlyUsageUsd") or 0)
        cycle = d.get("monthlyUsageCycle") or {}
        start = datetime.fromisoformat(cycle["startAt"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(cycle["endAt"].replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001 - no answer: fall back to the per-call cap alone
        return None
    budget = float(os.environ.get("APIFY_MONTHLY_USD") or 4.5)
    hard = float(((d.get("limits") or {}).get("maxMonthlyUsageUsd")) or budget)
    budget = min(budget, hard)
    days = max(1.0, (end - start).total_seconds() / 86400)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds() / 86400
    # today's share is spendable from the start of the day
    return spent, budget * min(1.0, (math.floor(elapsed) + 1) / days)


def _run(ctx, actor, payload, log_name):
    token = os.environ["APIFY_TOKEN"]
    key = "limitPerSource" if "limitPerSource" in payload else "limit"
    limit = payload.get(key) or 100
    price = PRICE.get(actor, 0.002)
    with _budget_lock:          # parallel sources must not all read the same "room left"
        daily = float(os.environ.get("APIFY_DAILY_USD") or float(os.environ.get("APIFY_MONTHLY_USD") or 4.5) / 30)
        today = _today_spent()
        room, why = daily - today, f"${today:.3f} of today's ${daily:.2f} (APIFY_DAILY_USD)"
        cycle = _allowance(ctx, token)
        if cycle is not None and cycle[1] - cycle[0] < room:
            room, why = cycle[1] - cycle[0], f"${cycle[0]:.2f} of ${cycle[1]:.2f} this cycle (APIFY_MONTHLY_USD)"
        # fewer results rather than none: the call is cut to what the budget still pays for
        fits = int((room - START_USD) / price) if room > START_USD else 0
        if fits < 10:
            ctx.log(f"  {log_name}: skipped - Apify budget used: {why}")
            return []
        if fits < limit:
            ctx.log(f"  {log_name}: {fits} result(s) instead of {limit} - Apify budget: {why}")
            payload = dict(payload, **{key: fits})
            limit = fits
    url = RUN_SYNC.format(actor=actor.replace("/", "~"))
    r = ctx.http.post(url, json=payload, params={"token": token, "timeout": 240, "memory": 1024},
                      timeout=280, retries=0)
    if r.status_code == 408:
        with _budget_lock:      # a timed-out run is still billed for what it scraped
            _add_spent(limit * price + START_USD)
        ctx.log(f"  {log_name}: actor timed out; partial results dropped")
        return []
    if r.status_code >= 400:
        raise RuntimeError(f"apify {actor}: HTTP {r.status_code} {r.text[:120]}")
    data = r.json()
    data = data if isinstance(data, list) else []
    with _budget_lock:
        _add_spent(len(data) * PRICE.get(actor, 0.002) + START_USD)
    return data


def _window_days(ctx):
    """The run's window as whole days (rounded up) - the actors only take days."""
    return math.ceil(ctx.window_hours / 24) if ctx.window_hours else None


def _ms_to_date(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


class _ApifyBase(Source):
    needs_env = ("APIFY_TOKEN",)
    homepage = "https://apify.com/"
    sub = ""

    def enabled(self):
        return super().enabled() and self.sub in _enabled_sources()

    def _experience(self, ctx):
        y = ctx.user_years
        if isinstance(y, (list, tuple)):
            y = y[0]
        try:
            return int(float(y)) if y is not None else None
        except (TypeError, ValueError):
            return None


class ApifyNaukri(_ApifyBase):
    key = "apify-naukri"
    name = "Naukri (Apify)"
    sub = "naukri"
    countries = ["IN"]
    actor = "valig/naukri-jobs-scraper"

    def search(self, ctx, country):
        out, seen = [], set()
        days = _window_days(ctx)
        age = next((a for a in (1, 3, 7, 15, 30) if days and days <= a), "30")
        for kw in ctx.keywords():
            payload = {"keywords": kw, "location": "India", "sort": "f", "jobAge": str(age),
                       "limit": min(ctx.max_per_source, 100)}
            exp = self._experience(ctx)
            if exp is not None:
                payload["experience"] = exp
            for it in _run(ctx, self.actor, payload, self.name):
                jid = str(it.get("id") or "")
                url = it.get("url") or ""
                if not jid or jid in seen or not url:
                    continue
                seen.add(jid)
                exp_ = it.get("experience") or {}
                sal = it.get("salary") or {}
                skills = (it.get("skills") or {})
                desc = it.get("description") or {}
                locs = ", ".join(l.get("label", "") for l in (it.get("locations") or []) if l.get("label"))
                j = self.job(
                    title=clean_title(it.get("title") or ""), company=clean_company((it.get("company") or {}).get("name", "")),
                    url=url if url.startswith("http") else "https://www.naukri.com" + url, country=country,
                    location=normalize_ws(locs or "India"),
                    posted=_ms_to_date(it.get("createdDate")) or parse_date(it.get("createdDateText")),
                    posted_raw=it.get("createdDate") or it.get("createdDateText") or "",   # epoch ms / "2 hours ago"
                    salary=normalize_ws(sal.get("label") or ""),
                    snippet=normalize_ws(desc.get("short") or "")[:400],
                    description=normalize_ws(desc.get("full") or ""),
                    skills=list(skills.get("preferred") or []) + list(skills.get("other") or []),
                    employment_type=it.get("employmentType") or "",
                    query=kw, id=f"nk{jid}",
                )
                for k, attr in (("minimum", "exp_min"), ("maximum", "exp_max")):
                    m = re.search(r"\d+(?:\.\d+)?", str(exp_.get(k) or ""))
                    if m:
                        setattr(j, attr, float(m.group()))
                j.extra.update({"naukri_id": jid, "company_apply": bool(it.get("companyApplyJob")),
                                "applicants": it.get("applyCount"), "rating": ((it.get("ambitionBox") or {}).get("companyInfo") or {}).get("AggregateRating")})
                if it.get("wfhType") in ("2", "Remote", "remote"):
                    j.remote = True
                out.append(j.finalize())
        return out


class ApifyIndeed(_ApifyBase):
    key = "apify-indeed"
    name = "Indeed (Apify)"
    sub = "indeed"
    countries = sorted(INDEED_COUNTRIES)
    actor = "valig/indeed-jobs-scraper"

    def search(self, ctx, country):
        out, seen = [], set()
        cname = COUNTRIES.get(country, {}).get("name", country)
        window = _window_days(ctx)
        days = next((d for d in (1, 3, 7, 14) if window and window <= d), "14")
        for kw in ctx.keywords():
            payload = {"country": "uk" if country == "GB" else country.lower(), "title": kw, "location": cname,
                       "limit": min(ctx.max_per_source, 100), "datePosted": str(days)}
            for it in _run(ctx, self.actor, payload, self.name):
                jid = str(it.get("key") or "")
                url = it.get("jobUrl") or it.get("url") or ""
                if not jid or jid in seen or not url or it.get("expired"):
                    continue
                seen.add(jid)
                loc = it.get("location") or {}
                sal = it.get("baseSalary") or {}
                salary = ""
                if sal.get("min") or sal.get("max"):
                    salary = " - ".join(f"{int(v):,}" for v in (sal.get("min"), sal.get("max")) if v) + " " + (sal.get("currencyCode") or "")
                j = self.job(
                    title=clean_title(it.get("title") or ""), company=clean_company((it.get("employer") or {}).get("name") or ""),
                    url=url, country=country,
                    location=normalize_ws(", ".join(x for x in (loc.get("city"), loc.get("admin1Code"), loc.get("countryName")) if x)),
                    posted=parse_date(it.get("datePublished")) or parse_date(it.get("dateOnIndeed")),
                    posted_raw=it.get("datePublished") or it.get("dateOnIndeed") or "",
                    salary=salary.strip(), snippet=normalize_ws((it.get("description") or {}).get("text") or "")[:400],
                    description=normalize_ws((it.get("description") or {}).get("text") or ""),
                    query=kw, id=f"in{jid}",
                )
                j.extra.update({"indeed_key": jid, "company_site": (it.get("employer") or {}).get("corporateWebsite") or ""})
                out.append(j.finalize())
        return out


class ApifyLinkedIn(_ApifyBase):
    key = "apify-linkedin"
    name = "LinkedIn (Apify)"
    sub = "linkedin"
    actor = "curious_coder/linkedin-jobs-scraper"

    def search(self, ctx, country):
        out, seen = [], set()
        meta = ctx.country_meta(country)
        location = meta.get("linkedin") or meta.get("name") or country
        h = ctx.window_hours
        posted = "past24Hours" if h and h <= 24 else ("pastWeek" if h and h <= 168 else "pastMonth")
        for kw in ctx.keywords():
            payload = {"keywords": kw, "location": location, "datePosted": posted, "scrapeCompany": False,
                       "limitPerSource": min(ctx.max_per_source, 100)}
            for it in _run(ctx, self.actor, payload, self.name):
                jid = str(it.get("id") or "")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                j = self.job(
                    title=clean_title(it.get("title") or ""), company=clean_company(it.get("companyName") or ""),
                    url=f"https://www.linkedin.com/jobs/view/{jid}", country=country,
                    location=normalize_ws(it.get("location") or ""), posted=parse_date(it.get("postedAt")),
                    posted_raw=it.get("postedAt") or "",   # ISO timestamp or "3 hours ago", depending on the card
                    salary=normalize_ws(it.get("salary") or ""),
                    snippet=normalize_ws(it.get("descriptionText") or "")[:400],
                    description=normalize_ws(it.get("descriptionText") or ""),
                    employment_type=it.get("employmentType") or "", seniority=it.get("seniorityLevel") or "",
                    query=kw, id=f"li{jid}",
                )
                j.extra["linkedin_id"] = jid
                if it.get("applyUrl"):
                    j.extra["apply_url"] = it["applyUrl"]
                if it.get("jobPosterName"):
                    j.extra["poster"] = {"name": it.get("jobPosterName"), "title": it.get("jobPosterTitle") or "",
                                         "url": it.get("jobPosterProfileUrl") or ""}
                if it.get("companyWebsite"):
                    j.extra["company_site"] = it["companyWebsite"]
                if re.search(r"\bremote\b", (it.get("location") or "") + " " + (it.get("title") or ""), re.I):
                    j.remote = True
                out.append(j.finalize())
        return out
