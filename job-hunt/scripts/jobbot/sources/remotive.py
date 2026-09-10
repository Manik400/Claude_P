"""Remotive - remote jobs API with keyword search."""
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source
from .remote_util import assign_country

API = "https://remotive.com/api/remote-jobs"


class Remotive(Source):
    key = "remotive"
    name = "Remotive"
    remote_only = True
    homepage = "https://remotive.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            data = ctx.http.get_json(API, params={"search": kw, "limit": 100})
            for it in data.get("jobs") or []:
                jid = str(it.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                title = clean_title(it.get("title", ""))
                desc = html_to_text(it.get("description") or "")
                tags = [t for t in (it.get("tags") or []) if t]
                if ctx.relevance(title, " ".join(tags) + " " + desc[:600]) <= 0:
                    continue
                posted = parse_date(it.get("publication_date"))
                if not ctx.fresh(posted):
                    continue
                loc = normalize_ws(it.get("candidate_required_location") or "")
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
                    salary=normalize_ws(it.get("salary") or ""),
                    snippet=desc[:400],
                    description=desc,
                    skills=tags,
                    employment_type=(it.get("job_type") or "").replace("_", " "),
                    query=kw,
                )
                j.extra["eligible"] = eligible
                out.append(j.finalize())
                if len(out) >= ctx.max_per_source:
                    return out
        return out
