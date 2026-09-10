"""LinkedIn public (guest) job search - no login needed, ~10 cards per page."""
import re

from ..textutil import clean_company, clean_title, parse_date, soup, html_to_text, normalize_ws
from .base import Source

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


class LinkedIn(Source):
    key = "linkedin"
    name = "LinkedIn"
    homepage = "https://www.linkedin.com/jobs/"

    def search(self, ctx, country):
        meta = ctx.country_meta(country)
        location = meta.get("linkedin") or meta.get("name") or country
        codes = ctx.linkedin_codes()
        out, seen = [], set()
        for kw in ctx.keywords():
            start = 0
            empty_pages = 0
            while len(out) < ctx.max_per_source and start <= 240:
                params = {"keywords": kw, "location": location, "start": start}
                if codes:
                    params["f_E"] = codes
                if ctx.days:
                    params["f_TPR"] = f"r{int(ctx.days) * 86400}"
                r = ctx.http.get(SEARCH_URL, params=params)
                if r.status_code != 200 or not r.text.strip():
                    break
                cards = self._parse(r.text, country, kw)
                if not cards:
                    empty_pages += 1
                    if empty_pages >= 1:
                        break
                added = 0
                for j in cards:
                    if j.id in seen:
                        continue
                    seen.add(j.id)
                    out.append(j)
                    added += 1
                if len(cards) < 10:
                    break
                start += len(cards)
        return out

    def _parse(self, markup, country, kw):
        s = soup(markup)
        jobs = []
        for card in s.select("div.base-card, li > div.base-search-card"):
            urn = card.get("data-entity-urn", "")
            m = re.search(r"jobPosting:(\d+)", urn)
            link = card.select_one("a.base-card__full-link")
            href = link.get("href", "") if link else ""
            if not m:
                m = re.search(r"-(\d{6,})\?", href) or re.search(r"/view/(\d{6,})", href)
            if not m:
                continue
            jid = m.group(1)
            title = card.select_one("h3.base-search-card__title")
            company = card.select_one("h4.base-search-card__subtitle")
            loc = card.select_one("span.job-search-card__location")
            date = card.select_one("time")
            salary = card.select_one("span.job-search-card__salary-info")
            j = self.job(
                title=clean_title(title.get_text(" ", strip=True) if title else ""),
                company=clean_company(company.get_text(" ", strip=True) if company else ""),
                url=f"https://www.linkedin.com/jobs/view/{jid}",
                country=country,
                location=normalize_ws(loc.get_text(" ", strip=True) if loc else ""),
                posted=parse_date(date.get("datetime") if date else None) or parse_date(date.get_text(strip=True) if date else None),
                salary=normalize_ws(salary.get_text(" ", strip=True) if salary else ""),
                query=kw,
                id=f"li{jid}",
            )
            j.extra["linkedin_id"] = jid
            if re.search(r"\bremote\b", j.location, re.I) or re.search(r"\bremote\b", j.title, re.I):
                j.remote = True
            jobs.append(j.finalize())
        return jobs

    def fetch_details(self, ctx, job):
        """Full description + criteria from the guest posting endpoint."""
        jid = job.extra.get("linkedin_id")
        if not jid:
            return None
        r = ctx.http.get(POSTING_URL.format(id=jid))
        if r.status_code != 200 or not r.text.strip():
            return None
        s = soup(r.text)
        desc = s.select_one("div.show-more-less-html__markup")
        text = html_to_text(str(desc)) if desc else ""
        for item in s.select("li.description__job-criteria-item"):
            h = item.select_one("h3")
            v = item.select_one("span")
            if not h or not v:
                continue
            label = h.get_text(strip=True).lower()
            value = v.get_text(" ", strip=True)
            if "seniority" in label:
                job.extra["seniority_level"] = value
            elif "employment" in label:
                job.employment_type = value
        return text
