"""JSearch (RapidAPI) - Google-for-Jobs aggregator that also carries Indeed/Glassdoor/LinkedIn postings.
Set RAPIDAPI_KEY (free tier at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)."""
import os

from ..config import COUNTRIES
from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

API = "https://jsearch.p.rapidapi.com/search"


class JSearch(Source):
    key = "jsearch"
    name = "JSearch (Google Jobs)"
    needs_env = ("RAPIDAPI_KEY",)
    homepage = "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"

    def search(self, ctx, country):
        out, seen = [], set()
        cname = COUNTRIES.get(country, {}).get("name", country)
        headers = {"X-RapidAPI-Key": os.environ["RAPIDAPI_KEY"], "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
        date_posted = "month" if not ctx.days or ctx.days > 7 else "week"
        for kw in ctx.keywords():
            params = {"query": f"{kw} in {cname}", "country": country.lower(), "date_posted": date_posted,
                      "page": 1, "num_pages": 2}
            data = ctx.http.get_json(API, params=params, headers=headers)
            for it in data.get("data") or []:
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
