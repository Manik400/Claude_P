"""Landing.jobs - European tech jobs, public JSON API."""
import re

from ..config import COUNTRIES, REMOTE
from ..textutil import clean_title, html_to_text, normalize_ws, parse_date
from .base import Source

API = "https://landing.jobs/api/v1/jobs"
EU = ["DE", "NL", "ES", "FI", "GB", "IE", "FR", "SE", "NO", "DK", "CH", "AT", "PT", "IT", "PL", "BE"]


class LandingJobs(Source):
    key = "landingjobs"
    name = "Landing.jobs"
    countries = EU
    homepage = "https://landing.jobs/"

    def __init__(self):
        self._cache = {}

    def _fetch(self, ctx):
        key = tuple(ctx.keywords())
        if key in self._cache:
            return self._cache[key]
        items = []
        for kw in ctx.keywords():
            offset = 0
            while offset < 300:
                data = ctx.http.get_json(API, params={"limit": 50, "offset": offset, "q": kw})
                if not isinstance(data, list) or not data:
                    break
                items.extend(data)
                if len(data) < 50:
                    break
                offset += 50
        self._cache[key] = items
        return items

    def search(self, ctx, country):
        out, seen = [], set()
        for it in self._fetch(ctx):
            jid = str(it.get("id"))
            codes = {(l.get("country_code") or "").upper() for l in (it.get("locations") or [])}
            if country != REMOTE and country not in codes:
                continue
            if country == REMOTE and not it.get("remote"):
                continue
            if jid in seen:
                continue
            seen.add(jid)
            title = clean_title(it.get("title", ""))
            desc = html_to_text((it.get("role_description") or "") + " " + (it.get("main_requirements") or ""))
            tags = [t for t in (it.get("tags") or []) if t]
            if ctx.relevance(title, " ".join(tags) + " " + desc[:600]) <= 0:
                continue
            posted = parse_date(it.get("published_at") or it.get("updated_at"))
            if not ctx.fresh(posted):
                continue
            url = it.get("url", "")
            m = re.search(r"landing\.jobs/at/([^/]+)/", url)
            company = m.group(1).replace("-", " ").title() if m else ""
            lo, hi, cur = it.get("gross_salary_low"), it.get("gross_salary_high"), it.get("currency_code") or ""
            salary = f"{lo:,}-{hi:,} {cur}".replace(",", " ") if lo and hi else ""
            cities = [f"{l.get('city')}" for l in (it.get("locations") or []) if (l.get("country_code") or "").upper() == country]
            j = self.job(
                title=title,
                company=company,
                url=url,
                country=country,
                location=normalize_ws(", ".join(c for c in cities if c)) or COUNTRIES.get(country, {}).get("name", ""),
                remote=bool(it.get("remote")),
                posted=posted,
                salary=salary,
                snippet=desc[:400],
                description=desc,
                skills=tags,
                employment_type=it.get("type") or "",
            )
            if it.get("relocation_paid"):
                j.extra["relocation_paid"] = True
            out.append(j.finalize())
            if len(out) >= ctx.max_per_source:
                break
        return out
