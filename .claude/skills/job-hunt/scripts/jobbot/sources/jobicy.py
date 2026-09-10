"""Jobicy - remote jobs API (keyword tag search)."""
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source
from .remote_util import assign_country

API = "https://jobicy.com/api/v2/remote-jobs"


class Jobicy(Source):
    key = "jobicy"
    name = "Jobicy"
    remote_only = True
    homepage = "https://jobicy.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            data = ctx.http.get_json(API, params={"count": 50, "tag": kw})
            for it in data.get("jobs") or []:
                jid = str(it.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                title = clean_title(it.get("jobTitle", ""))
                desc = html_to_text(it.get("jobDescription") or it.get("jobExcerpt") or "")
                if ctx.relevance(title, desc[:600]) <= 0:
                    continue
                posted = parse_date(it.get("pubDate"))
                if not ctx.fresh(posted):
                    continue
                geo = normalize_ws(it.get("jobGeo") or "")
                code, eligible = assign_country(geo, ctx)
                if code is None:
                    continue
                lo, hi, cur = it.get("annualSalaryMin"), it.get("annualSalaryMax"), it.get("salaryCurrency") or ""
                salary = f"{lo} - {hi} {cur}".strip() if lo and hi else ""
                j = self.job(
                    title=title,
                    company=clean_company(it.get("companyName", "")),
                    url=it.get("url", ""),
                    country=code,
                    location=f"Remote · {geo}" if geo else "Remote",
                    remote=True,
                    posted=posted,
                    salary=salary,
                    snippet=html_to_text(it.get("jobExcerpt") or "")[:400] or desc[:400],
                    description=desc,
                    skills=[t for t in (it.get("jobIndustry") or []) if t],
                    employment_type=", ".join(it.get("jobType") or []),
                    seniority={"Senior": "senior", "Junior": "junior", "Lead": "lead", "Entry": "junior"}.get(it.get("jobLevel", ""), ""),
                    query=kw,
                )
                j.extra["eligible"] = eligible
                out.append(j.finalize())
                if len(out) >= ctx.max_per_source:
                    return out
        return out
