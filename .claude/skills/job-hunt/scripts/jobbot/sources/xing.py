"""XING Jobs (DACH) - server-rendered search page."""
import re

from ..textutil import clean_company, clean_title, normalize_ws, soup
from .base import Source

URL = "https://www.xing.com/jobs/search"
LOCATION = {"DE": "Deutschland", "AT": "Österreich", "CH": "Schweiz"}


class Xing(Source):
    key = "xing"
    name = "XING"
    countries = ["DE", "AT", "CH"]
    homepage = "https://www.xing.com/jobs"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 6:
                params = {"keywords": kw, "location": LOCATION.get(country, ""), "page": page}
                html = ctx.http.get_html(URL, params=params)
                cards = self._parse(html, country, kw)
                if not cards:
                    if page == 1 and params["location"]:
                        # retry once without location if the country string is not understood
                        html = ctx.http.get_html(URL, params={"keywords": kw, "page": 1})
                        cards = self._parse(html, country, kw)
                        if not cards:
                            break
                    else:
                        break
                new = 0
                for j in cards:
                    if j.id in seen:
                        continue
                    seen.add(j.id)
                    out.append(j)
                    new += 1
                if new == 0:
                    break
                page += 1
        return out

    def _parse(self, html, country, kw):
        s = soup(html)
        jobs = []
        for card in s.select('article[data-testid="job-search-result"]'):
            a = card.select_one("a[href]")
            href = a.get("href", "") if a else ""
            if not href:
                continue
            m = re.search(r"-(\d{6,})$", href.split("?")[0])
            title = card.select_one('[data-testid="job-teaser-list-title"]') or card.select_one("h2")
            company = card.select_one('p[class*="Company"]')
            loc = card.select_one('div[class*="multi-location"] p') or card.select_one('p[class*="Location"]')
            loc_text = normalize_ws(loc.get_text(" ", strip=True)) if loc else ""
            loc_text = re.sub(r"\+\s*\d+\s*more", "", loc_text).strip("  ")
            facts = " ".join(t.get_text(" ", strip=True) for t in card.select('[class*="job-teaser-facts"] span'))
            salary = ""
            sm = re.search(r"(\d[\d.,]*\s*(?:€|EUR|CHF)[^|]*)", facts)
            if sm:
                salary = normalize_ws(sm.group(1))
            j = self.job(
                title=clean_title(title.get_text(" ", strip=True) if title else card.get("aria-label", "").split(". Click")[0]),
                company=clean_company(company.get_text(" ", strip=True) if company else ""),
                url="https://www.xing.com" + href.split("?")[0] if href.startswith("/") else href,
                country=country,
                location=loc_text,
                salary=salary,
                remote=True if re.search(r"remote|homeoffice|home office", (loc_text + " " + facts), re.I) else None,
                query=kw,
                id=f"xing{m.group(1)}" if m else "",
            )
            jobs.append(j.finalize())
        return jobs
