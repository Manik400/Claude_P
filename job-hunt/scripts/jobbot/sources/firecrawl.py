"""Firecrawl web search (optional, FIRECRAWL_API_KEY) - runs the fallback site: queries for blocked platforms."""
import os
import re

from ..fallback import fallback_queries
from ..textutil import clean_company, clean_title, normalize_ws
from .base import Source

API = "https://api.firecrawl.dev/v1/search"


def parse_result_title(text):
    """'Python Developer - Acme GmbH - Berlin | Indeed.com' -> (title, company)."""
    t = normalize_ws(text or "")
    t = re.sub(r"\s*[|\-–]\s*(Indeed\.com|Indeed|Glassdoor|Naukri\.com|StepStone|Jora|hirist\.tech|Hirist|LinkedIn|Jobly|CareerCross|GaijinPot).*$", "", t, flags=re.I)
    parts = [p.strip() for p in re.split(r"\s+[-–|]\s+", t) if p.strip()]
    if not parts:
        return "", ""
    title = parts[0]
    company = parts[1] if len(parts) > 1 else ""
    m = re.match(r"(.+?)\s+hiring\s+(.+?)\s+in\s+", t, re.I)  # LinkedIn style
    if m:
        company, title = m.group(1), m.group(2)
    return clean_title(title), clean_company(company)


class FirecrawlSearch(Source):
    key = "firecrawl"
    name = "Web search (Firecrawl)"
    needs_env = ("FIRECRAWL_API_KEY",)
    homepage = "https://firecrawl.dev/"

    def search(self, ctx, country):
        out, seen = [], set()
        headers = {"Authorization": f"Bearer {os.environ['FIRECRAWL_API_KEY']}", "Content-Type": "application/json"}
        for q in fallback_queries(ctx.roles, [country], ctx.user_years):
            if len(out) >= ctx.max_per_source:
                break
            r = ctx.http.post(API, json={"query": q["query"], "limit": 10}, headers=headers)
            if r.status_code != 200:
                continue
            for it in (r.json().get("data") or []):
                url = it.get("url", "")
                if not url or url in seen:
                    continue
                if q["url_must_contain"] and q["url_must_contain"] not in url:
                    continue
                seen.add(url)
                title, company = parse_result_title(it.get("title", ""))
                if not title or ctx.relevance(title, it.get("description", "")) <= 0:
                    continue
                j = self.job(
                    source=q["platform"], source_name=q["platform_name"],
                    title=title, company=company, url=url, country=country,
                    location=q["country_name"],
                    snippet=normalize_ws(it.get("description") or "")[:400],
                    query=q["role"],
                )
                j.extra["from_fallback"] = True
                out.append(j.finalize())
        return out
