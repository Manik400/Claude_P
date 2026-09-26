"""JSearch (RapidAPI) - Google-for-Jobs aggregator that also carries Indeed/Glassdoor/LinkedIn postings.
Set RAPIDAPI_KEY (free tier at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)."""
import json
import os
import threading
import time
from pathlib import Path

from ..config import COUNTRIES
from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

# JSearch moved its search to /search-v2 (the old /search now answers 404) and nests the
# results as {"data": {"jobs": [...], "cursor": ...}}.
API = "https://jsearch.p.rapidapi.com/search-v2"

# The free plan is ~200 requests a month and the job-hunt search runs every hour, so calls
# are budgeted per day (JSEARCH_DAILY_MAX, default 6 = ~180/month). The count lives next to
# the other per-PC state; on GitHub Actions each run starts fresh, so keep that search daily.
USAGE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "JobHuntPhone" / "jsearch_usage.json"
_usage_lock = threading.Lock()


def _take_budget() -> bool:
    limit = int(os.environ.get("JSEARCH_DAILY_MAX") or 6)
    today = time.strftime("%Y-%m-%d")
    with _usage_lock:
        try:
            used = json.loads(USAGE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            used = {}
        if used.get("day") != today:
            used = {"day": today, "n": 0}
        if used["n"] >= limit:
            return False
        used["n"] += 1
        USAGE.parent.mkdir(parents=True, exist_ok=True)
        USAGE.write_text(json.dumps(used), encoding="utf-8")
        return True


class JSearch(Source):
    key = "jsearch"
    name = "JSearch (Google Jobs)"
    needs_env = ("RAPIDAPI_KEY",)
    homepage = "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"

    def search(self, ctx, country):
        out, seen = [], set()
        cname = COUNTRIES.get(country, {}).get("name", country)
        headers = {"X-RapidAPI-Key": os.environ["RAPIDAPI_KEY"], "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
        # smallest bucket the API offers that still covers the window
        h = ctx.window_hours
        date_posted = ("today" if h and h <= 24 else "3days" if h and h <= 72
                       else "week" if h and h <= 168 else "month")
        for kw in ctx.keywords():
            if not _take_budget():
                ctx.log(f"  JSearch: today's budget of {os.environ.get('JSEARCH_DAILY_MAX') or 6} request(s) is used; skipping")
                break
            params = {"query": f"{kw} in {cname}", "country": country.lower(), "date_posted": date_posted,
                      "page": 1, "num_pages": 1}
            data = ctx.http.get_json(API, params=params, headers=headers)
            rows = data.get("data") or []
            if isinstance(rows, dict):
                rows = rows.get("jobs") or []
            for it in rows:
                jid = str(it.get("job_id"))
                if jid in seen:
                    continue
                seen.add(jid)
                exp = (it.get("job_required_experience") or {}).get("required_experience_in_months")
                lo, hi = it.get("job_min_salary"), it.get("job_max_salary")
                salary = f"{int(lo):,} - {int(hi):,} {it.get('job_salary_currency') or ''}".strip() if lo and hi else ""
                loc = ", ".join(x for x in (it.get("job_city"), it.get("job_state"), it.get("job_country")) if x)
                j = self.job(
                    title=clean_title(it.get("job_title", "")),
                    company=clean_company(it.get("employer_name", "")),
                    url=it.get("job_apply_link") or it.get("job_google_link") or "",
                    country=country,
                    location=normalize_ws(loc),
                    remote=bool(it.get("job_is_remote")) if it.get("job_is_remote") is not None else None,
                    posted=parse_date(it.get("job_posted_at_datetime_utc")),
                    posted_raw=it.get("job_posted_at_datetime_utc") or "",
                    salary=salary,
                    snippet=normalize_ws(it.get("job_description") or "")[:400],
                    description=normalize_ws(it.get("job_description") or ""),
                    employment_type=it.get("job_employment_type") or "",
                    exp_min=(exp / 12.0) if exp else None,
                    query=kw,
                )
                j.extra["via"] = it.get("job_publisher", "")
                out.append(j.finalize())
                if len(out) >= ctx.max_per_source:
                    return out
        return out
