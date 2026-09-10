"""Wellfound (ex-AngelList Talent) - public role/location landing pages carry job data in __NEXT_DATA__."""
import json
import re

from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date, slugify
from .base import Source

PAGE = "https://wellfound.com/role/l/{role}/{loc}"
FALLBACK_ROLES = ["software-engineer"]


class Wellfound(Source):
    key = "wellfound"
    name = "Wellfound"
    homepage = "https://wellfound.com/jobs"

    def search(self, ctx, country):
        loc = ctx.country_meta(country).get("wellfound")
        if not loc:
            return []
        out, seen = [], set()
        role_slugs = []
        for r in ctx.roles:
            s = slugify(r)
            if s and s not in role_slugs:
                role_slugs.append(s)
        for fb in FALLBACK_ROLES:
            if fb not in role_slugs:
                role_slugs.append(fb)
        for slug in role_slugs:
            if len(out) >= ctx.max_per_source:
                break
            try:
                r = ctx.http.get(PAGE.format(role=slug, loc=loc), allow_block=True)
            except Exception:
                continue
            if r.status_code != 200:
                continue
            jobs = self._parse(r.text, country, slug)
            for j in jobs:
                if j.id in seen:
                    continue
                if ctx.relevance(j.title, j.snippet) <= 0:
                    continue
                seen.add(j.id)
                if ctx.fresh(j.posted):
                    out.append(j)
        return out

    def _parse(self, html, country, slug):
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))["props"]["pageProps"]["apolloState"]["data"]
        except Exception:
            return []
        company_of = {}
        for k, v in data.items():
            if k.startswith("StartupResult:") and isinstance(v, dict):
                for ref in v.get("highlightedJobListings") or []:
                    if isinstance(ref, dict) and ref.get("__ref"):
                        company_of[ref["__ref"]] = v
        jobs = []
        for k, v in data.items():
            if not k.startswith("JobListingSearchResult:") or not isinstance(v, dict):
                continue
            jid = str(v.get("id") or k.split(":")[1])
            startup = company_of.get(k, {})
            desc = html_to_text(v.get("description") or "")
            locs = v.get("locationNames") or []
            comp = v.get("compensation") or ""
            j = self.job(
                title=clean_title(v.get("title") or v.get("primaryRoleTitle") or ""),
                company=clean_company(startup.get("name", "")),
                url=f"https://wellfound.com/jobs/{jid}-{v.get('slug') or slug}",
                country=country,
                location=normalize_ws(", ".join(locs) if locs else ""),
                remote=bool(v.get("remote")) if v.get("remote") is not None else None,
                posted=None,  # liveStartAt is the original post date; listings stay live for years
                salary=normalize_ws(comp),
                snippet=desc[:400],
                description=desc,
                employment_type=v.get("jobType") or "",
                exp_min=v.get("yearsExperienceMin"),
                exp_max=v.get("yearsExperienceMax"),
                query=slug,
                id=f"wf{jid}",
            )
            if startup.get("companySize"):
                j.extra["company_size"] = startup["companySize"]
            jobs.append(j.finalize())
        return jobs
