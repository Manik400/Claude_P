"""Japan Dev - curated English-friendly tech jobs in Japan (listing pages, filtered client-side)."""
import re

from ..textutil import clean_company, clean_title, normalize_ws, soup
from .base import Source

URL = "https://japan-dev.com/jobs"


class JapanDev(Source):
    key = "japandev"
    name = "Japan Dev"
    countries = ["JP"]
    searchable = False
    homepage = URL

    def search(self, ctx, country):
        out, seen = [], set()
        page = 1
        while page <= 5 and len(out) < ctx.max_per_source:
            html = ctx.http.get_html(URL, params={"page": page} if page > 1 else None)
            items = self._parse(html, country)
            if not items:
                break
            new = 0
            for j in items:
                if j.id in seen:
                    continue
                seen.add(j.id)
                new += 1
                if ctx.relevance(j.title, " ".join(j.skills) + " " + j.snippet) > 0:
                    out.append(j)
            if new == 0:
                break
            page += 1
        return out

    def _parse(self, html, country):
        s = soup(html)
        jobs = []
        for li in s.select("li.job-item"):
            a = li.select_one("a.job-item__title")
            if not a:
                continue
            ct = li.select_one(".job-item__contract-type")
            ct_text = normalize_ws(ct.get_text(" ", strip=True)) if ct else ""
            company = ct_text.split("・")[0] if ct_text else ""
            tags = [normalize_ws(t.get_text(" ", strip=True)) for t in li.select(".job-top-tag-list span") if t.get_text(strip=True)]
            tech = [normalize_ws(t.get_text(" ", strip=True)) for t in li.select(".technology-list li") if t.get_text(strip=True)]
            loc = [normalize_ws(t.get_text(" ", strip=True)) for t in li.select(".job__tag-desc")]
            title = clean_title(a.get_text(" ", strip=True))
            j = self.job(
                title=title,
                company=clean_company(company),
                url="https://japan-dev.com" + a.get("href"),
                country=country,
                location=", ".join(loc) or "Japan",
                remote=True if any(re.search(r"full remote|fully remote|remote ok", t, re.I) for t in tags) else None,
                skills=tech,
                snippet=", ".join(tags),
            )
            jobs.append(j.finalize())
        return jobs
