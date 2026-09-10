"""Tecnoempleo (Spain, IT jobs) - server-rendered listing."""
import re

from ..textutil import clean_company, clean_title, normalize_ws, parse_date, soup
from .base import Source

URL = "https://www.tecnoempleo.com/ofertas-trabajo/"


class Tecnoempleo(Source):
    key = "tecnoempleo"
    name = "Tecnoempleo"
    countries = ["ES"]
    homepage = "https://www.tecnoempleo.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 5:
                html = ctx.http.get_html(URL, params={"te": kw, "pagina": page})
                cards = self._parse(html, country, kw)
                new = 0
                for j in cards:
                    if j.id in seen:
                        continue
                    seen.add(j.id)
                    if ctx.fresh(j.posted):
                        out.append(j)
                    new += 1
                if new == 0 or len(cards) < 20:
                    break
                page += 1
        return out

    def _parse(self, html, country, kw):
        s = soup(html)
        jobs = []
        for card in s.select("div.p-3.border.rounded.mb-3.bg-white"):
            a = card.select_one("h3 a[href]")
            if not a:
                continue
            company = card.select_one('a[title^="Ofertas de Empleo"]') or card.select_one("a.link-muted")
            right = card.select_one("div.col-12.col-lg-3")
            right_text = normalize_ws(right.get_text(" ", strip=True)) if right else ""
            small = card.select_one("span.d-block.d-lg-none")
            small_text = normalize_ws(small.get_text(" ", strip=True)) if small else ""
            date = parse_date(right_text) or parse_date(small_text)
            loc = ""
            b = (right or card).select_one("b")
            if b:
                loc = normalize_ws(b.get_text(strip=True))
            mode = re.search(r"\((Híbrido|Hibrido|Remoto|Teletrabajo|Presencial)\)", right_text + " " + small_text, re.I)
            if mode:
                loc = f"{loc} · {mode.group(1)}"
            snippet_el = card.select_one("span.hidden-md-down")
            snippet = normalize_ws(snippet_el.get_text(" ", strip=True)) if snippet_el else ""
            badges = [normalize_ws(x.get_text(strip=True)) for x in card.select("span.badge") if x.get_text(strip=True)
                      and x.get_text(strip=True).lower() not in ("nueva", "actualizada", "destacada")]
            j = self.job(
                title=clean_title(a.get("title") or a.get_text(" ", strip=True)),
                company=clean_company(company.get_text(" ", strip=True) if company else ""),
                url=a.get("href"),
                country=country,
                location=loc or "Spain",
                posted=date,
                snippet=snippet[:400],
                skills=badges,
                remote=True if mode and mode.group(1).lower() in ("remoto", "teletrabajo") else None,
                query=kw,
            )
            jobs.append(j.finalize())
        return jobs
