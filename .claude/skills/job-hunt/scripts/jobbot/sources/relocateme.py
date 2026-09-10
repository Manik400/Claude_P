"""Relocate.me - international tech jobs with relocation support (listing pages; country comes from the URL)."""
import re

from ..config import resolve_country
from ..textutil import clean_company, clean_title, normalize_ws, soup
from .base import Source

URL = "https://relocate.me/international-jobs"
JOB_RE = re.compile(r"^/([a-z-]+)/([a-z-]+)/([a-z0-9-]+)/([a-z0-9-]+)-(\d+)$")


class RelocateMe(Source):
    key = "relocateme"
    name = "Relocate.me"
    searchable = False
    homepage = URL

    def __init__(self):
        self._cache = None

    def _all_jobs(self, ctx):
        if self._cache is not None:
            return self._cache
        jobs = []
        seen = set()
        for page in range(1, 7):
            html = ctx.http.get_html(URL, params={"page": page} if page > 1 else None)
            s = soup(html)
            found = 0
            for box in s.select("div.job__title"):
                a = box.select_one("a[href]")
                if not a:
                    continue
                m = JOB_RE.match(a.get("href", ""))
                if not m:
                    continue
                found += 1
                if m.group(5) in seen:
                    continue
                seen.add(m.group(5))
                b = a.select_one("b")
                title = clean_title(b.get_text(" ", strip=True) if b else a.get_text(" ", strip=True))
                after = normalize_ws(a.get_text(" ", strip=True))
                city = after.split(" in ", 1)[1] if " in " in after else m.group(2).replace("-", " ").title()
                comp_el = box.find_previous("p")
                company = clean_company(comp_el.get_text(" ", strip=True) if comp_el else m.group(3).replace("-", " ").title())
                jobs.append(dict(title=title, company=company, url="https://relocate.me" + m.group(0),
                                 country=resolve_country(m.group(1).replace("-", " ")), city=city))
            if found == 0:
                break
        self._cache = jobs
        return jobs

    def search(self, ctx, country):
        out = []
        for it in self._all_jobs(ctx):
            if it["country"] != country:
                continue
            if ctx.relevance(it["title"]) <= 0:
                continue
            j = self.job(title=it["title"], company=it["company"], url=it["url"], country=country,
                         location=it["city"], snippet="Relocation support advertised")
            j.extra["relocation"] = True
            out.append(j.finalize())
        return out
