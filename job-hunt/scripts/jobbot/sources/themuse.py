"""The Muse - public jobs API, filtered by city location strings (no keyword search)."""
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source

API = "https://www.themuse.com/api/public/jobs"


class TheMuse(Source):
    key = "themuse"
    name = "The Muse"
    searchable = False
    homepage = "https://www.themuse.com/jobs"

    def search(self, ctx, country):
        locations = ctx.country_meta(country).get("muse") or []
        if not locations:
            return []
        out, seen = [], set()
        page = 1
        while page <= 2 and len(out) < ctx.max_per_source:  # slow API, few tech roles: keep it cheap
            params = [("page", page), ("descending", "true")] + [("location", loc) for loc in locations]
            data = ctx.http.get_json(API, params=params)
            items = data.get("results") or []
            if not items:
                break
            for it in items:
                jid = str(it.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                title = clean_title(it.get("name", ""))
                desc = html_to_text(it.get("contents") or "")
                if ctx.relevance(title, desc[:600]) <= 0:
                    continue
                posted = parse_date(it.get("publication_date"))
                if not ctx.fresh(posted):
                    continue
                levels = [l.get("name", "") for l in (it.get("levels") or [])]
                locs = [l.get("name", "") for l in (it.get("locations") or [])]
                j = self.job(
                    title=title,
                    company=clean_company((it.get("company") or {}).get("name", "")),
                    url=(it.get("refs") or {}).get("landing_page", ""),
                    country=country,
                    location=normalize_ws(", ".join(l for l in locs if l)[:120]),
                    remote=True if any("remote" in l.lower() for l in locs) else None,
                    posted=posted,
                    snippet=desc[:400],
                    description=desc,
                    seniority={"Senior Level": "senior", "Mid Level": "mid", "Entry Level": "junior", "Internship": "intern"}.get(levels[0], "") if levels else "",
                )
                out.append(j.finalize())
            if page >= int(data.get("page_count") or 1):
                break
            page += 1
        return out
