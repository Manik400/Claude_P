"""Arbeitnow - free job board API, Germany focused (plus remote). No keyword search: filtered client-side."""
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source

API = "https://www.arbeitnow.com/api/job-board-api"


class Arbeitnow(Source):
    key = "arbeitnow"
    name = "Arbeitnow"
    countries = ["DE"]
    searchable = False
    homepage = "https://www.arbeitnow.com/"

    def search(self, ctx, country):
        out = []
        page = 1
        while page <= 4 and len(out) < ctx.max_per_source:
            data = ctx.http.get_json(API, params={"page": page})
            items = data.get("data") or []
            if not items:
                break
            for it in items:
                title = clean_title(it.get("title", ""))
                tags = [t for t in (it.get("tags") or []) if t]
                desc = html_to_text(it.get("description") or "")
                if ctx.relevance(title, " ".join(tags) + " " + desc[:800]) <= 0:
                    continue
                posted = parse_date(it.get("created_at"))
                if not ctx.fresh(posted):
                    continue
                j = self.job(
                    title=title,
                    company=clean_company(it.get("company_name", "")),
                    url=it.get("url", ""),
                    country=country,
                    location=normalize_ws(it.get("location") or "Germany"),
                    remote=bool(it.get("remote")),
                    posted=posted,
                    snippet=desc[:400],
                    description=desc,
                    skills=tags,
                    employment_type=", ".join(it.get("job_types") or []),
                )
                out.append(j.finalize())
            if not (data.get("links") or {}).get("next"):
                break
            page += 1
        return out
