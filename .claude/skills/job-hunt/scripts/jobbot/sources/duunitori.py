"""Duunitori (Finland) - public JSON API. Search is AND-based per word, so we also query single terms."""
from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

API = "https://duunitori.fi/api/v1/jobentries"


class Duunitori(Source):
    key = "duunitori"
    name = "Duunitori"
    countries = ["FI"]
    homepage = "https://duunitori.fi/"

    def search(self, ctx, country):
        out, seen = [], set()
        queries = list(ctx.keywords())
        for t in ctx.strong_terms():
            if t not in queries:
                queries.append(t)
        for q in queries:
            url, params = API, {"search": q, "format": "json"}
            pages = 0
            while url and pages < 5 and len(out) < ctx.max_per_source:
                data = ctx.http.get_json(url, params=params)
                params = None  # `next` already carries the query string
                for it in data.get("results") or []:
                    slug = it.get("slug", "")
                    if not slug or slug in seen:
                        continue
                    title = clean_title(it.get("heading", ""))
                    desc = normalize_ws(it.get("descr") or "")
                    if ctx.relevance(title, desc[:600]) <= 0:
                        continue
                    seen.add(slug)
                    posted = parse_date(it.get("date_posted"))
                    if not ctx.fresh(posted):
                        continue
                    j = self.job(
                        title=title,
                        company=clean_company(it.get("company_name", "")),
                        url=f"https://duunitori.fi/tyopaikat/tyo/{slug}",
                        country=country,
                        location=normalize_ws(it.get("municipality_name") or "Finland"),
                        posted=posted,
                        snippet=desc[:400],
                        description=desc,
                        query=q,
                    )
                    out.append(j.finalize())
                url = data.get("next")
                pages += 1
        return out
