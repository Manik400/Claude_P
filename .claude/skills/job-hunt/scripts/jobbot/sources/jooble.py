"""Jooble - aggregator API (free key: https://jooble.org/api/about). Set JOOBLE_API_KEY."""
import os

from ..config import COUNTRIES
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source

API = "https://jooble.org/api/{key}"


class Jooble(Source):
    key = "jooble"
    name = "Jooble"
    needs_env = ("JOOBLE_API_KEY",)
    homepage = "https://jooble.org/"

    def search(self, ctx, country):
        out, seen = [], set()
        location = COUNTRIES.get(country, {}).get("name", country)
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 4:
                body = {"keywords": kw, "location": location, "page": page}
                r = ctx.http.post(API.format(key=os.environ["JOOBLE_API_KEY"]), json=body)
                r.raise_for_status()
                data = r.json()
                items = data.get("jobs") or []
                if not items:
                    break
                for it in items:
                    jid = str(it.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    posted = parse_date(it.get("updated"))
                    if not ctx.fresh(posted):
                        continue
                    j = self.job(
                        title=clean_title(it.get("title", "")),
                        company=clean_company(it.get("company", "")),
                        url=it.get("link", ""),
                        country=country,
                        location=normalize_ws(it.get("location") or location),
                        posted=posted,
                        salary=normalize_ws(it.get("salary") or ""),
                        snippet=html_to_text(it.get("snippet") or "")[:400],
                        employment_type=it.get("type") or "",
                        query=kw,
                    )
                    j.extra["via"] = it.get("source", "")
                    out.append(j.finalize())
                page += 1
        return out
