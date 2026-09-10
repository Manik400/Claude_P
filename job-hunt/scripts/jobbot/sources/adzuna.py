"""Adzuna - aggregator API (free key: https://developer.adzuna.com). Set ADZUNA_APP_ID and ADZUNA_APP_KEY."""
import os

from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

API = "https://api.adzuna.com/v1/api/jobs/{cc}/search/{page}"
SUPPORTED = ["GB", "US", "AT", "AU", "BE", "BR", "CA", "CH", "DE", "ES", "FR", "IN", "IT", "MX", "NL", "NZ", "PL", "SG", "ZA"]


class Adzuna(Source):
    key = "adzuna"
    name = "Adzuna"
    countries = SUPPORTED
    needs_env = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")
    homepage = "https://www.adzuna.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 4:
                params = {"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"],
                          "what": kw, "results_per_page": 50, "content-type": "application/json"}
                if ctx.days:
                    params["max_days_old"] = int(ctx.days)
                data = ctx.http.get_json(API.format(cc=country.lower(), page=page), params=params)
                items = data.get("results") or []
                if not items:
                    break
                for it in items:
                    jid = str(it.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    lo, hi = it.get("salary_min"), it.get("salary_max")
                    salary = f"{int(lo):,} - {int(hi):,}" if lo and hi else ""
                    j = self.job(
                        title=clean_title(it.get("title", "")),
                        company=clean_company((it.get("company") or {}).get("display_name", "")),
                        url=it.get("redirect_url", ""),
                        country=country,
                        location=normalize_ws((it.get("location") or {}).get("display_name", "")),
                        posted=parse_date(it.get("created")),
                        salary=salary,
                        snippet=normalize_ws(it.get("description") or "")[:400],
                        employment_type=it.get("contract_type") or "",
                        query=kw,
                    )
                    out.append(j.finalize())
                if len(items) < 50:
                    break
                page += 1
        return out
