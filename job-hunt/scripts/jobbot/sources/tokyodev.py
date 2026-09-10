"""TokyoDev - English-speaking developer jobs in Japan (single listing page, filtered client-side)."""
import re

from ..textutil import clean_company, clean_title, normalize_ws, soup
from .base import Source

URL = "https://www.tokyodev.com/jobs"


class TokyoDev(Source):
    key = "tokyodev"
    name = "TokyoDev"
    countries = ["JP"]
    searchable = False
    homepage = URL

    def search(self, ctx, country):
        html = ctx.http.get_html(URL)
        s = soup(html)
        out = []
        for li in s.select('li[id^="company_"]'):
            comp = li.select_one("h3 a")
            company = clean_company(comp.get_text(" ", strip=True)) if comp else ""
            for block in li.select('div[data-collapsable-list-target="item"]'):
                a = block.select_one('a[href*="/jobs/"]')
                if not a:
                    continue
                tags = [normalize_ws(t.get_text(" ", strip=True)) for t in block.select("a.tag")]
                salary = next((t for t in tags if "¥" in t or "$" in t), "")
                skills = [t for t in tags if t != salary and not re.search(r"remote|japanese|abroad|visa|hybrid", t, re.I)]
                flags = [t for t in tags if re.search(r"remote|japanese|abroad|visa|hybrid", t, re.I)]
                title = clean_title(a.get_text(" ", strip=True))
                if ctx.relevance(title, " ".join(skills)) <= 0:
                    continue
                j = self.job(
                    title=title,
                    company=company,
                    url="https://www.tokyodev.com" + a.get("href"),
                    country=country,
                    location="Japan" + (" · " + ", ".join(flags) if flags else ""),
                    remote=True if any("fully remote" in f.lower() for f in flags) else None,
                    salary=salary,
                    skills=skills,
                    snippet=", ".join(flags),
                )
                out.append(j.finalize())
                if len(out) >= ctx.max_per_source:
                    return out
        return out
