"""InfoJobs (Spain) - server-rendered results (only the first few cards per page are in the HTML)."""
import re

from ..textutil import clean_company, clean_title, normalize_ws, parse_date, soup
from .base import Source

URL = "https://www.infojobs.net/jobsearch/search-results/list.xhtml"


class InfoJobs(Source):
    key = "infojobs"
    name = "InfoJobs"
    countries = ["ES"]
    homepage = "https://www.infojobs.net/"
    blocked_note = "InfoJobs sometimes shows a bot check; open the direct search link instead."

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 8:
                html = ctx.http.get_html(URL, params={"keyword": kw, "page": page, "sortBy": "PUBLICATION_DATE"})
                cards = self._parse(html, country, kw)
                new = 0
                for j in cards:
                    if j.id in seen:
                        continue
                    seen.add(j.id)
                    new += 1
                    if ctx.fresh(j.posted):
                        out.append(j)
                if new == 0:
                    break
                page += 1
        return out

    def _parse(self, html, country, kw):
        s = soup(html)
        jobs = []
        for h2 in s.select("h2.ij-OfferCardContent-description-title"):
            a = h2.select_one("a[href]")
            if not a:
                continue
            href = a.get("href", "")
            if href.startswith("//"):
                href = "https:" + href
            href = href.split("?")[0]
            card = h2.find_parent(class_=re.compile("ij-OfferCardContent")) or h2.parent
            comp = card.select_one(".ij-OfferCardContent-description-subtitle-link") or card.select_one("h3")
            items = [normalize_ws(li.get_text(" ", strip=True)) for li in card.select("li.ij-OfferCardContent-description-list-item")]
            loc = items[0] if items else "Spain"
            mode = next((i for i in items if re.search(r"híbrido|hibrido|presencial|teletrabajo|remoto", i, re.I)), "")
            date = next((parse_date(i) for i in items if re.search(r"hace|\d{1,2}/\d{1,2}/\d{4}|hoy|ayer", i, re.I)), None)
            salary = next((i for i in items if "€" in i), "")
            contract = next((i for i in items if re.search(r"indefinido|temporal|autónomo|prácticas|formativo|freelance", i, re.I)), "")
            exp = next((i for i in items if re.search(r"experiencia", i, re.I)), "")
            m = re.search(r"of-i([0-9a-f]+)", href)
            j = self.job(
                title=clean_title(a.get("aria-label") or a.get_text(" ", strip=True)),
                company=clean_company(comp.get_text(" ", strip=True) if comp else ""),
                url=href,
                country=country,
                location=normalize_ws(f"{loc}{(' · ' + mode) if mode else ''}"),
                posted=date,
                salary=salary,
                employment_type=contract,
                snippet=exp,
                remote=True if re.search(r"teletrabajo|remoto", mode, re.I) else None,
                query=kw,
                id=f"ij{m.group(1)[:12]}" if m else "",
            )
            jobs.append(j.finalize())
        return jobs
