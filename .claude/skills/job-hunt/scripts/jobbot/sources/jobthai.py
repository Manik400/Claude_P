"""JobThai (Thailand) - job data embedded in the page's __NEXT_DATA__ Apollo cache."""
import json
import re

from ..textutil import clean_company, clean_title, normalize_ws, parse_date
from .base import Source

URL = "https://www.jobthai.com/en/jobs"


class JobThai(Source):
    key = "jobthai"
    name = "JobThai"
    countries = ["TH"]
    homepage = "https://www.jobthai.com/en/"

    def search(self, ctx, country):
        out, seen = [], set()
        for kw in ctx.keywords():
            page = 1
            while len(out) < ctx.max_per_source and page <= 5:
                html = ctx.http.get_html(URL, params={"keyword": kw, "page": page})
                items = self._parse(html)
                if not items:
                    break
                new = 0
                for it in items:
                    jid = str(it.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    new += 1
                    prov = (it.get("province") or {}).get("name") or ""
                    dist = (it.get("district") or {}).get("name") or ""
                    tags = [t for t in (it.get("tags") or []) if t]
                    posted = parse_date(it.get("updatedAt"))
                    if not ctx.fresh(posted):
                        continue
                    j = self.job(
                        title=clean_title(it.get("jobTitle", "")),
                        company=clean_company(it.get("companyName", "")),
                        url=f"https://www.jobthai.com/en/company/job/{jid}",
                        country=country,
                        location=normalize_ws(", ".join(x for x in (dist, prov) if x)) or "Thailand",
                        posted=posted,
                        salary=normalize_ws(it.get("salary") or ""),
                        snippet=normalize_ws(it.get("workLocation") or ""),
                        skills=[t for t in tags if not re.search(r"hybrid|remote|work", t, re.I)],
                        remote=True if any(re.search(r"remote|work from home", t, re.I) for t in tags) else None,
                        query=kw,
                        id=f"jt{jid}",
                    )
                    out.append(j.finalize())
                if new == 0 or len(items) < 20:
                    break
                page += 1
        return out

    def _parse(self, html):
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return []
        try:
            root = json.loads(m.group(1))["props"]["apolloState"]["ROOT_QUERY"]
        except Exception:
            return []
        for k, v in root.items():
            if k.startswith("searchJobs(") and isinstance(v, dict):
                data = v.get("data") or {}
                items = data.get("data") if isinstance(data, dict) else None
                if isinstance(items, list):
                    return items
        return []
