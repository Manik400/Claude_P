"""Daijob (Japan, bilingual jobs) - server-rendered search results."""
import re

from ..textutil import clean_company, clean_title, normalize_ws, soup
from .base import Source

URL = "https://www.daijob.com/en/jobs/search_result"


class Daijob(Source):
    key = "daijob"
    name = "Daijob"
    countries = ["JP"]
    homepage = "https://www.daijob.com/en/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 4:
                html = ctx.http.get_html(URL, params={"keywords": kw, "page": page})
                cards = self._parse(html, country, kw)
                new = 0
                for j in cards:
                    if j.id in seen:
                        continue
                    seen.add(j.id)
                    new += 1
                    out.append(j)
                if new == 0 or len(cards) < 20:
                    break
                page += 1
        return out

    def _parse(self, html, country, kw):
        s = soup(html)
        jobs = []
        for card in s.select("article.job-card"):
            a = card.select_one("h2.job-card__title a[href]")
            if not a:
                continue
            m = re.search(r"/detail/(\d+)", a.get("href", ""))
            comp = card.select_one(".job-card__header-info .fw-bolder a") or card.select_one(".job-card__header-info a")
            level = next((normalize_ws(p.get_text(" ", strip=True)).replace("★", "").strip()
                          for p in card.select(".job-card__tags .pill") if "level" in p.get_text().lower()), "")
            details = {}
            for dl in card.select(".job-card__detail dl"):
                dts = dl.select("dt")
                dds = dl.select("dd")
                for dt, dd in zip(dts, dds):
                    details[normalize_ws(dt.get_text(" ", strip=True)).lower()] = normalize_ws(dd.get_text(" ", strip=True))
            loc = details.get("location", "Japan")
            loc = normalize_ws(loc.replace("Asia", "").strip())
            j = self.job(
                title=clean_title(a.get_text(" ", strip=True)),
                company=clean_company(comp.get_text(" ", strip=True) if comp else ""),
                url="https://www.daijob.com" + a.get("href"),
                country=country,
                location=loc or "Japan",
                salary=details.get("salary", "") if "depends" not in details.get("salary", "").lower() else "",
                snippet=(details.get("job description", "")[:400] + (" · Japanese: " + details["japanese level"] if details.get("japanese level") else "")),
                seniority={"senior level": "senior", "mid level": "mid", "entry level": "junior", "executive": "lead"}.get(level.lower(), ""),
                query=kw,
                id=f"dj{m.group(1)}" if m else "",
            )
            if level:
                j.extra["level"] = level
            if details.get("japanese level"):
                j.extra["japanese_level"] = details["japanese level"]
            jobs.append(j.finalize())
        return jobs
