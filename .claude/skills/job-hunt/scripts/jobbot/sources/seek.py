"""Seek family (Seek AU/NZ, JobsDB TH/HK, JobStreet SG/MY) - public JSON search API."""
from ..config import COUNTRIES
from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

BRAND = {"AU": "Seek", "NZ": "Seek", "TH": "JobsDB", "HK": "JobsDB", "SG": "JobStreet", "MY": "JobStreet"}


class Seek(Source):
    key = "seek"
    name = "Seek / JobsDB / JobStreet"
    countries = [c for c, m in COUNTRIES.items() if m.get("seek")]
    homepage = "https://www.seek.com.au/"

    def search(self, ctx, country):
        base, site_key, locale = ctx.country_meta(country)["seek"]
        brand = BRAND.get(country, "Seek")
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 8:
                params = {"siteKey": site_key, "sourcesystem": "houston", "keywords": kw, "page": page,
                          "pageSize": 22, "locale": locale}
                if ctx.days:
                    params["daterange"] = min(int(ctx.days), 31)
                data = ctx.http.get_json(f"{base}/api/jobsearch/v5/search", params=params)
                items = data.get("data") or []
                if not items:
                    break
                for it in items:
                    jid = str(it.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    locs = it.get("locations") or []
                    loc = locs[0].get("label") if locs and isinstance(locs[0], dict) else it.get("location", "")
                    arr = (it.get("workArrangements") or {}).get("displayText") or ""
                    teaser = normalize_ws(it.get("teaser") or "")
                    bullets = [normalize_ws(b) for b in (it.get("bulletPoints") or []) if b]
                    j = self.job(
                        source_name=brand,
                        title=clean_title(it.get("title", "")),
                        company=clean_company(it.get("companyName") or (it.get("advertiser") or {}).get("description", "")),
                        url=f"{base}/job/{jid}",
                        country=country,
                        location=normalize_ws(f"{loc} {('· ' + arr) if arr else ''}"),
                        posted=parse_date(it.get("listingDate")),
                        salary=normalize_ws(it.get("salaryLabel") or ""),
                        snippet=" ".join([teaser] + bullets),
                        employment_type=", ".join(it.get("workTypes") or []),
                        remote=True if "remote" in arr.lower() else (False if arr else None),
                        query=kw,
                    )
                    cls = it.get("classifications") or []
                    if cls:
                        j.extra["category"] = (cls[0].get("subclassification") or {}).get("description", "")
                    out.append(j.finalize())
                total = data.get("totalCount") or 0
                if page * 22 >= total:
                    break
                page += 1
        return out
