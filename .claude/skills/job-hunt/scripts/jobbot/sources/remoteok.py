"""RemoteOK - public JSON feed (tag-filtered), remote jobs."""
from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source
from .remote_util import assign_country

API = "https://remoteok.com/api"


class RemoteOK(Source):
    key = "remoteok"
    name = "RemoteOK"
    remote_only = True
    homepage = "https://remoteok.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        tags = ctx.strong_terms() or ["dev"]
        for tag in tags[:3]:
            data = ctx.http.get_json(API, params={"tag": tag})
            if not isinstance(data, list):
                continue
            for it in data:
                if not isinstance(it, dict) or not it.get("id"):
                    continue
                jid = str(it.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                title = clean_title(it.get("position") or it.get("title") or "")
                desc = html_to_text(it.get("description") or "")
                jtags = [t for t in (it.get("tags") or []) if t]
                if ctx.relevance(title, " ".join(jtags) + " " + desc[:600]) <= 0:
                    continue
                posted = parse_date(it.get("epoch") or it.get("date"))
                if not ctx.fresh(posted):
                    continue
                loc = normalize_ws(it.get("location") or "")
                code, eligible = assign_country(loc, ctx)
                if code is None:
                    continue
                lo, hi = it.get("salary_min") or 0, it.get("salary_max") or 0
                salary = f"${int(lo):,} - ${int(hi):,}" if lo and hi else ""
                j = self.job(
                    title=title,
                    company=clean_company(it.get("company", "")),
                    url=it.get("url") or it.get("apply_url") or "",
                    country=code,
                    location=f"Remote · {loc}" if loc else "Remote",
                    remote=True,
                    posted=posted,
                    salary=salary,
                    snippet=desc[:400],
                    description=desc,
                    skills=jtags,
                    query=tag,
                )
                j.extra["eligible"] = eligible
                out.append(j.finalize())
                if len(out) >= ctx.max_per_source:
                    return out
        return out
