"""Himalayas - remote jobs search API (free, no key; ~100k open postings)."""
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source
from .remote_util import assign_country

API = "https://himalayas.app/jobs/api/search"


class Himalayas(Source):
    key = "himalayas"
    name = "Himalayas"
    remote_only = True
    homepage = "https://himalayas.app/jobs"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            for page in (1, 2):
                data = ctx.http.get_json(API, params={"q": kw, "limit": 50, "page": page})
                rows = data.get("jobs") or []
                for it in rows:
                    jid = it.get("guid") or it.get("applicationLink")
                    if not jid or jid in seen:
                        continue
                    seen.add(jid)
                    title = clean_title(it.get("title", ""))
                    desc = html_to_text(it.get("description") or it.get("excerpt") or "")
                    cats = [c for c in (it.get("categories") or []) if c]
                    if ctx.relevance(title, " ".join(cats) + " " + desc[:600]) <= 0:
                        continue
                    loc = ", ".join(it.get("locationRestrictions") or []) or "Anywhere"
                    code, eligible = assign_country(loc, ctx)
                    if code is None:
                        continue
                    lo, hi = it.get("minSalary"), it.get("maxSalary")
                    salary = (f"{lo:,} - {hi:,} {it.get('currency') or ''} / {it.get('salaryPeriod') or 'year'}"
                              if lo and hi else "")
                    j = self.job(
                        title=title,
                        company=clean_company(it.get("companyName", "")),
                        url=it.get("applicationLink") or jid,
                        country=code,
                        location=f"Remote · {loc}",
                        remote=True,
                        posted=parse_date(it.get("pubDate")),
                        posted_raw=str(it.get("pubDate") or ""),
                        salary=salary,
                        snippet=normalize_ws(it.get("excerpt") or desc)[:400],
                        description=desc,
                        skills=cats[:10],
                        employment_type=it.get("employmentType") or "",
                        query=kw,
                    )
                    j.extra["eligible"] = eligible
                    j.extra["seniority"] = ", ".join(it.get("seniority") or [])
                    j.finalize()
                    ok, why = ctx.fresh_job(j)
                    if not ok and why == "old":
                        continue
                    out.append(j)
                    if len(out) >= ctx.max_per_source:
                        return out
                if len(rows) < 50:
                    break
        return out
