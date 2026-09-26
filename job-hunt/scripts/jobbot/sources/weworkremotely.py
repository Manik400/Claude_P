"""We Work Remotely - the programming / devops RSS feeds (free, no key)."""
import xml.etree.ElementTree as ET

from ..textutil import clean_company, clean_title, html_to_text, normalize_ws, parse_date
from .base import Source
from .remote_util import assign_country

FEEDS = (
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
)


class WeWorkRemotely(Source):
    key = "weworkremotely"
    name = "We Work Remotely"
    remote_only = True
    homepage = "https://weworkremotely.com/"

    def search(self, ctx, country):
        out, seen = [], set()
        for feed in FEEDS:
            r = ctx.http.get(feed)
            r.raise_for_status()
            for it in ET.fromstring(r.content).iter("item"):
                url = (it.findtext("link") or it.findtext("guid") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                # titles are "Company: Role"
                company, _, title = (it.findtext("title") or "").partition(":")
                if not title:
                    company, title = "", company
                title = clean_title(title)
                desc = html_to_text(it.findtext("description") or "")
                if ctx.relevance(title, (it.findtext("category") or "") + " " + desc[:600]) <= 0:
                    continue
                loc = normalize_ws(it.findtext("region") or "")
                code, eligible = assign_country(loc, ctx)
                if code is None:
                    continue
                j = self.job(
                    title=title,
                    company=clean_company(company),
                    url=url,
                    country=code,
                    location=f"Remote · {loc}" if loc else "Remote",
                    remote=True,
                    posted=parse_date(it.findtext("pubDate")),
                    posted_raw=it.findtext("pubDate") or "",
                    snippet=desc[:400],
                    description=desc,
                    employment_type=it.findtext("type") or "",
                    query=ctx.primary_role,
                )
                j.extra["eligible"] = eligible
                j.finalize()
                ok, why = ctx.fresh_job(j)
                if not ok and why == "old":
                    continue
                out.append(j)
                if len(out) >= ctx.max_per_source:
                    return out
        return out
