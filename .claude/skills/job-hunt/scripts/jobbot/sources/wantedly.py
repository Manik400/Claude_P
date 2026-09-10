"""Wantedly (Japan) - public projects API (hiring posts, mostly Japanese-language)."""
from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

API = "https://www.wantedly.com/api/v1/projects"


class Wantedly(Source):
    key = "wantedly"
    name = "Wantedly"
    countries = ["JP"]
    homepage = "https://www.wantedly.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 6:
                data = ctx.http.get_json(API, params={"q": kw, "page": page, "per_page": 20})
                items = data.get("data") or []
                if not items:
                    break
                for it in items:
                    pid = str(it.get("id"))
                    if pid in seen:
                        continue
                    seen.add(pid)
                    title = clean_title(it.get("title", ""))
                    desc = normalize_ws(it.get("description") or "")
                    looking = normalize_ws(it.get("looking_for") or "")
                    if ctx.relevance(title + " " + looking, desc[:800]) <= 0:
                        continue
                    posted = parse_date(it.get("published_at"))
                    if not ctx.fresh(posted):
                        continue
                    j = self.job(
                        title=title if not looking or looking in title else f"{title} ({looking})",
                        company=clean_company((it.get("company") or {}).get("name", "")),
                        url=f"https://www.wantedly.com/projects/{pid}",
                        country=country,
                        location=normalize_ws(it.get("location") or "Japan"),
                        posted=posted,
                        snippet=desc[:400],
                        description=desc,
                        query=kw,
                    )
                    out.append(j.finalize())
                meta = data.get("_metadata") or {}
                if page >= int(meta.get("total_pages") or 1):
                    break
                page += 1
        return out
