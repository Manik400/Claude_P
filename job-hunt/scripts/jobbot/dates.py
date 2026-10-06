"""Read the posting date off a job's own page, for the postings the board never dated.

A window like "last 24 hours" is only honest when every posting in the report can be
shown to be inside it. Boards often publish a date (not a time), or nothing at all -
Wellfound, Instahyre, XING, the Japan boards. The posting page itself usually knows:
a JobPosting JSON-LD block carries `datePosted`, meta tags carry a published time,
and the visible page says "Posted 3 days ago" or "Date posted: 12 Sep 2026".

    found = from_html(html)      -> (iso_date, iso_datetime | None, how) or (None, None, "")
    verify(ctx, jobs, ...)       fetch the pages of undated jobs, re-check the window

After verify(), a posting is either dated (and kept or dropped by the window) or still
undated after its page was read - those are kept, marked `extra.posted_checked = "none"`,
unless the context asks for strict dates (ctx.allow_undated False).
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .textutil import parse_when

_LD_RX = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
_META_RX = re.compile(r'<meta[^>]+(?:property|name|itemprop)=["\'](?:article:published_time|datePosted|date_posted|og:updated_time|publish[_-]?date|pubdate|dc\.date(?:\.issued)?)["\'][^>]*content=["\']([^"\']+)["\']', re.I)
_META_RX2 = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name|itemprop)=["\'](?:article:published_time|datePosted|date_posted|og:updated_time|publish[_-]?date|pubdate)["\']', re.I)
_TIME_RX = re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I)
# visible text: "Posted 3 days ago", "Posted on 12 Sep 2026", "Date posted: September 12, 2026", "Posted: Today", "2 hours ago"
_TEXT_RX = re.compile(r"(?:posted|published|date posted|posting date|listed|advertised|job posted)\s*(?:on|:|-|–)?\s*"
                      r"((?:\d{1,2}\s+)?(?:\d+\+?\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\s+ago|today|yesterday|just now|"
                      r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?|"
                      r"\d{1,2}[./-]\d{1,2}[./-]\d{4}|[a-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[a-z]{3,9}\.?\s+\d{4}))", re.I)
_AGO_RX = re.compile(r"\b(\d+\+?)\s*(minutes?|mins?|hours?|hrs?|days?|weeks?)\s+ago\b", re.I)


def _ld_items(html):
    for m in _LD_RX.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except ValueError:
            # some pages wrap several objects or leave trailing commas; try the outermost braces
            try:
                data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            except ValueError:
                continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict):
                yield it
                for sub in it.get("@graph") or []:
                    if isinstance(sub, dict):
                        yield sub


def from_html(html):
    """(iso_date, iso_datetime | None, source) for the posting date a page states, else (None, None, "")."""
    if not html:
        return None, None, ""
    head = html[:600000]
    for it in _ld_items(head):
        if str(it.get("@type") or "").lower() in ("jobposting",) and it.get("datePosted"):
            d, at = parse_when(str(it["datePosted"]))
            if d:
                return d, at, "json-ld"
    for rx in (_META_RX, _META_RX2):
        m = rx.search(head)
        if m:
            d, at = parse_when(m.group(1))
            if d:
                return d, at, "meta"
    text = re.sub(r"<[^>]+>", " ", head)
    text = re.sub(r"\s+", " ", text)
    m = _TEXT_RX.search(text)
    if m:
        d, at = parse_when(m.group(1))
        if d:
            return d, at, "text"
    m = _AGO_RX.search(text[:20000])
    if m:
        d, at = parse_when(m.group(0))
        if d:
            return d, at, "text"
    m = _TIME_RX.search(head)
    if m:
        d, at = parse_when(m.group(1))
        if d:
            return d, at, "time-tag"
    return None, None, ""


def _needs_check(ctx, job):
    """Does the window need more than this job's card said? Under a day a date is not enough."""
    window = ctx.window_hours
    if not window:
        return False
    if getattr(job, "posted_at", None):
        return False
    if window < 24:
        return True
    return not getattr(job, "posted", None)


def verify(ctx, jobs, limit=80, workers=6, log=print, fetch_html=None):
    """Read the pages of the postings whose age the board did not state well enough.

    Returns (kept_jobs, dropped_count, checked_count). `fetch_html(job) -> str | None`
    can replace the HTTP fetch (tests). Jobs the window cannot judge even after their
    page was read are kept when ctx.allow_undated, else dropped.
    """
    todo = [j for j in jobs if _needs_check(ctx, j) and str(getattr(j, "url", "")).startswith("http")]
    todo.sort(key=lambda j: -(getattr(j, "relevance", 0) or 0))
    todo = todo[:limit]
    if not todo:
        return list(jobs), 0, 0

    def fetch(job):
        if fetch_html is not None:
            return fetch_html(job)
        r = ctx.http.get(job.url, allow_block=True, retries=0)
        if r.status_code != 200 or "html" not in (r.headers.get("content-type") or "").lower():
            return None
        return r.text

    def work(job):
        try:
            html = fetch(job)
        except Exception:  # noqa: BLE001 - a page that will not load is just still undated
            html = None
        d, at, how = from_html(html) if html else (None, None, "")
        return job, d, at, how

    dated = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as ex:
        for job, d, at, how in ex.map(work, todo):
            if d:
                job.posted = d
                if at:
                    job.posted_at = at
                job.extra["posted_source"] = "page:" + how
                dated += 1
            job.extra["posted_checked"] = how or "none"
    kept, dropped = [], 0
    checked = set(id(j) for j in todo)
    for j in jobs:
        if id(j) not in checked:
            kept.append(j)
            continue
        ok, _why = ctx.fresh_job(j)    # "undated" only comes back when ctx does not allow undated postings
        if ok:
            kept.append(j)
        else:
            dropped += 1
    log(f"dates: checked {len(todo)} posting page(s) with no usable time on them; {dated} now dated, "
        f"{dropped} dropped as outside the window" + ("" if ctx.allow_undated else " or still undated"))
    return kept, dropped, len(todo)
