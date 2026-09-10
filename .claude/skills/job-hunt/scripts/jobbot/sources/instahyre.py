"""Instahyre (India) - public search API used by the site's landing pages."""
from ..textutil import clean_company, clean_title, normalize_ws
from .base import Source

API = "https://www.instahyre.com/api/v1/job_search"


class Instahyre(Source):
    key = "instahyre"
    name = "Instahyre"
    countries = ["IN"]
    homepage = "https://www.instahyre.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            offset = 0
            while len(out) < ctx.max_per_source and offset < 200:
                data = ctx.http.get_json(API, params={"company_size": 0, "job_type": 0, "limit": 35, "offset": offset, "q": kw})
                items = data.get("objects") or []
                if not items:
                    break
                for it in items:
                    jid = str(it.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    title = clean_title(it.get("title") or it.get("candidate_title") or "")
                    kws = [k for k in (it.get("keywords") or []) if k]
                    if ctx.relevance(title, " ".join(kws)) <= 0:
                        continue
                    emp = it.get("employer") or {}
                    j = self.job(
                        title=title,
                        company=clean_company(emp.get("company_name", "")),
                        url=it.get("public_url") or f"https://www.instahyre.com/job-{jid}/",
                        country=country,
                        location=normalize_ws(it.get("locations") or "India"),
                        skills=kws,
                        snippet=normalize_ws(emp.get("company_tagline") or ""),
                        query=kw,
                        id=f"ih{jid}",
                    )
                    out.append(j.finalize())
                meta = data.get("meta") or {}
                if not meta.get("next"):
                    break
                offset += 35
        return out
