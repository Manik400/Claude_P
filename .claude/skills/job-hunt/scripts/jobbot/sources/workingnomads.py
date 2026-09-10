"""Working Nomads - public remote job feed (no search; filtered client-side)."""
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source
from .remote_util import assign_country

API = "https://www.workingnomads.com/api/exposed_jobs/"


class WorkingNomads(Source):
    key = "workingnomads"
    name = "Working Nomads"
    remote_only = True
    searchable = False
    homepage = "https://www.workingnomads.com/jobs"

    def search(self, ctx, country):
        out = []
        data = ctx.http.get_json(API)
        if not isinstance(data, list):
            return out
        for it in data:
            title = clean_title(it.get("title", ""))
            desc = html_to_text(it.get("description") or "")
            tags = [t.strip() for t in (it.get("tags") or "").split(",") if t.strip()]
            if ctx.relevance(title, " ".join(tags) + " " + desc[:600]) <= 0:
                continue
            posted = parse_date(it.get("pub_date"))
            if not ctx.fresh(posted):
                continue
            loc = normalize_ws(it.get("location") or "")
            code, eligible = assign_country(loc, ctx)
            if code is None:
                continue
            j = self.job(
                title=title,
                company=clean_company(it.get("company_name", "")),
                url=it.get("url", ""),
                country=code,
                location=f"Remote · {loc}" if loc else "Remote",
                remote=True,
                posted=posted,
                snippet=desc[:400],
                description=desc,
                skills=tags,
            )
            j.extra["eligible"] = eligible
            out.append(j.finalize())
            if len(out) >= ctx.max_per_source:
                break
        return out
