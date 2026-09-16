"""Readers for the public job-board APIs that company career pages are built on.

fetch(http, company, keep, roles, details, place) -> (jobs, total, recruiters)
    keep(title) -> bool   decides which postings are worth keeping (and, for SmartRecruiters / Workday,
                          worth the extra request for the full description)
    place(codes) -> bool  SmartRecruiters / Workday only: skip postings in countries nobody asked for
                          before spending a request on their description (other boards return everything at once)
    total                 how many postings the company has open in all
    recruiters            names of the people who posted the kept jobs, when the board says so
"""
import html as htmlmod

from ..config import REMOTE
from ..models import Job
from ..textutil import html_to_text, parse_date
from . import geo


def _job(c, title, url, locations, iso, text, posted, remote=None, department="", employment="", recruiter=""):
    locs = [l for l in locations if l]
    codes = [x for x in (geo.from_iso(i) or geo.resolve(i) or "" for i in iso if i) if x and x != "*"]
    for code in geo.codes(locs):
        if code not in codes:
            codes.append(code)
    if remote and not codes:
        codes = [REMOTE]
    if len(codes) > 1 and REMOTE in codes:
        codes.remove(REMOTE)
    location = " / ".join(dict.fromkeys(locs))[:160]
    job = Job(source=c.ats, source_name=c.name, title=title or "", company=c.name, url=url or c.careers,
              country=codes[0] if codes else "", location=location, remote=remote, posted=parse_date(posted),
              description=text or "", snippet=(text or "")[:300], employment_type=employment or "",
              extra={"countries": codes, "department": department or "", "recruiter": recruiter or ""})
    return job.finalize()


def _greenhouse(http, c, keep, roles, details, place):
    d = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{c.board}/jobs", params={"content": "true"})
    rows = d.get("jobs") or []
    out = []
    for j in rows:
        if not keep(j.get("title", "")):
            continue
        offices = [o.get("location") or o.get("name") for o in j.get("offices") or []]
        text = html_to_text(htmlmod.unescape(j.get("content") or ""))
        loc = (j.get("location") or {}).get("name", "")
        out.append(_job(c, j.get("title"), j.get("absolute_url"), [loc] + offices, [], text,
                        j.get("first_published") or j.get("updated_at"), remote=("remote" in loc.lower()) or None,
                        department=", ".join(x.get("name", "") for x in j.get("departments") or [])))
    return out, len(rows), []


def _lever(http, c, keep, roles, details, place):
    rows = http.get_json(f"https://api.lever.co/v0/postings/{c.board}", params={"mode": "json"})
    rows = rows if isinstance(rows, list) else []
    out = []
    for p in rows:
        if not keep(p.get("text", "")):
            continue
        cat = p.get("categories") or {}
        parts = [p.get("descriptionPlain") or ""]
        for block in p.get("lists") or []:
            parts.append((block.get("text") or "") + ": " + html_to_text(block.get("content") or ""))
        parts.append(p.get("additionalPlain") or "")
        out.append(_job(c, p.get("text"), p.get("hostedUrl"), [cat.get("location")] + list(cat.get("allLocations") or []),
                        [p.get("country")], " ".join(parts), p.get("createdAt"),
                        remote=(p.get("workplaceType") == "remote") or None,
                        department=cat.get("department") or cat.get("team") or "", employment=cat.get("commitment") or ""))
    return out, len(rows), []


def _ashby(http, c, keep, roles, details, place):
    d = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{c.board}")
    rows = [p for p in d.get("jobs") or [] if p.get("isListed") is not False]
    out = []
    for p in rows:
        if not keep(p.get("title", "")):
            continue
        locs, iso = [p.get("location")], []
        for place in [p] + list(p.get("secondaryLocations") or []):
            if place is not p:
                locs.append(place.get("location"))
            iso.append((((place.get("address") or {}).get("postalAddress")) or {}).get("addressCountry"))
        text = p.get("descriptionPlain") or html_to_text(p.get("descriptionHtml") or "")
        out.append(_job(c, p.get("title"), p.get("jobUrl"), locs, iso, text, p.get("publishedAt"),
                        remote=bool(p.get("isRemote")) or None, department=p.get("department") or "",
                        employment=p.get("employmentType") or ""))
    return out, len(rows), []


def _smartrecruiters(http, c, keep, roles, details, place):
    base = f"https://api.smartrecruiters.com/v1/companies/{c.board}/postings"
    rows, offset, total = [], 0, 0
    while offset < 3000:
        d = http.get_json(base, params={"limit": 100, "offset": offset})
        page = d.get("content") or []
        total = d.get("totalFound") or total
        rows.extend(page)
        offset += 100
        if not page or offset >= total:
            break
    wanted = []
    for q in rows:
        loc = q.get("location") or {}
        where = geo.codes(loc.get("fullLocation")) + [x for x in [geo.from_iso(loc.get("country"))] if x]
        if keep(q.get("name", "")) and place(where):
            wanted.append(q)
    out, recruiters = [], []
    for i, p in enumerate(wanted):
        loc = p.get("location") or {}
        text, url, recruiter = "", f"https://jobs.smartrecruiters.com/{c.board}/{p.get('id')}", ""
        if i < details:
            try:
                det = http.get_json(p["ref"])
                sections = ((det.get("jobAd") or {}).get("sections")) or {}
                text = " ".join(html_to_text(s.get("text") or "") for s in sections.values() if isinstance(s, dict))
                url = det.get("postingUrl") or url
                recruiter = ((det.get("creator") or {}).get("name")) or ""
            except Exception:  # noqa: BLE001 - keep the posting without its description
                pass
        if recruiter and recruiter not in recruiters:
            recruiters.append(recruiter)
        out.append(_job(c, p.get("name"), url, [loc.get("fullLocation"), loc.get("city")], [loc.get("country")], text,
                        p.get("releasedDate"), remote=bool(loc.get("remote")) or None,
                        department=((p.get("department") or {}).get("label")) or "",
                        employment=((p.get("typeOfEmployment") or {}).get("label")) or "", recruiter=recruiter))
    return out, total or len(rows), recruiters


def _recruitee(http, c, keep, roles, details, place):
    d = http.get_json(f"https://{c.board}.recruitee.com/api/offers/")
    rows = d.get("offers") or []
    out = []
    for o in rows:
        if not keep(o.get("title", "")):
            continue
        locs = [o.get("location"), o.get("city"), o.get("country")]
        for l in o.get("locations") or []:
            if isinstance(l, dict):
                locs.append(", ".join(x for x in (l.get("city"), l.get("country")) if x))
        text = html_to_text((o.get("description") or "") + " " + (o.get("requirements") or ""))
        out.append(_job(c, o.get("title"), o.get("careers_url"), locs, [o.get("country_code")], text,
                        o.get("published_at"), remote=bool(o.get("remote")) or None,
                        department=o.get("department") or "", employment=o.get("employment_type_code") or ""))
    return out, len(rows), []


def _workday(http, c, keep, roles, details, place):
    host, tenant, site = c.board.split("/", 2)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    found, total = {}, 0
    for role in roles or [""]:
        offset = 0
        while offset < 200:
            r = http.post(base + "/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": role})
            r.raise_for_status()
            d = r.json()
            page = d.get("jobPostings") or []
            total = max(total, d.get("total") or 0)
            for p in page:
                if p.get("externalPath") and keep(p.get("title", "")) and place(geo.codes(p.get("locationsText"))):
                    found.setdefault(p["externalPath"], p)
            offset += 20
            if len(page) < 20:
                break
    out = []
    for i, (path, p) in enumerate(found.items()):
        locs, iso, text, posted = [p.get("locationsText")], [], "", parse_date(p.get("postedOn"))
        url = f"https://{host}/{site}{path}"
        if i < details:
            try:
                info = (http.get_json(base + path) or {}).get("jobPostingInfo") or {}
                text = html_to_text(info.get("jobDescription") or "")
                locs = [info.get("location")] + list(info.get("additionalLocations") or [])
                iso = [(info.get("country") or {}).get("descriptor")]
                url = info.get("externalUrl") or url
                posted = info.get("startDate") or posted
            except Exception:  # noqa: BLE001
                pass
        out.append(_job(c, p.get("title"), url, locs, iso, text, posted))
    return out, total, []


READERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby, "smartrecruiters": _smartrecruiters,
           "recruitee": _recruitee, "workday": _workday}


def fetch(http, company, keep, roles, details=40, place=None):
    return READERS[company.ats](http, company, keep, roles, details, place or (lambda codes: True))


def probe(http, slug):
    """Which job boards answer for `slug`? -> list of (ats, open_jobs). Used by `careers_bot.py find`."""
    hits = []
    checks = [
        ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", lambda d: len(d.get("jobs") or [])),
        ("lever", f"https://api.lever.co/v0/postings/{slug}?mode=json", lambda d: len(d) if isinstance(d, list) else 0),
        ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{slug}", lambda d: len(d.get("jobs") or [])),
        ("smartrecruiters", f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1", lambda d: d.get("totalFound") or 0),
        ("recruitee", f"https://{slug}.recruitee.com/api/offers/", lambda d: len(d.get("offers") or [])),
    ]
    for ats, url, count in checks:
        try:
            r = http.get(url, retries=0)
            if r.status_code == 200:
                n = count(r.json())
                if n:
                    hits.append((ats, n))
        except Exception:  # noqa: BLE001
            continue
    return hits
