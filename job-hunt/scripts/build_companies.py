"""Grow assets/companies.txt from public sources - every added company verified live.

    python job-hunt/scripts/build_companies.py                 all sources, append what verifies
    python job-hunt/scripts/build_companies.py --dry-run       count only, write nothing
    python job-hunt/scripts/build_companies.py --sources seed,yc

Sources (all public, fetched fresh each run):
  newgrad   SimplifyJobs New-Grad / internship listings, speedyapply and vanshb03 new-grad
            lists - 0-2 YOE by definition, and their links name the job board directly
  yc        the Y Combinator directory (yc-oss API): active companies that are hiring
  hww       hiring-without-whiteboards (remote-friendly, practical interviews)
  remote    established-remote (remote-first companies)
  runs      job boards seen in your own job-hunt runs (~/Documents/JobHunt/*/jobs.json)
  seed      assets/companies_seed.txt - Indian unicorns and GCCs, relocation / visa
            sponsors in EU, Japan, SEA, Middle East, remote-first, AI labs
  ind       the Netherlands IND register of recognised sponsors (highly-skilled migrant visa)
  uk        the UK Home Office register of licensed sponsors, Skilled Worker, tech-sounding names
  atslists  the per-ATS company lists of Feashliaa/job-board-aggregator (MIT): ~28k Greenhouse,
            Lever, Ashby, BambooHR and Workday boards. Only boards with at least one open
            software-engineering role today are added, so the list stays "hiring SWE now"

A company is added only when its board answers: Greenhouse, Lever, Ashby,
SmartRecruiters, Workable, Recruitee, Breezy, Personio, BambooHR, or Workday (from a
link that names it).
A board found from a link counts even with no open jobs today; a board guessed
from a name must have open jobs, so a slug that happens to exist for someone
else is not taken. Nothing is ever removed from companies.txt; new rows go under
"# ---- discovered by build_companies.py". Probe results are cached in
assets/probe_cache.json, so a re-run only asks about new names.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from jobbot.careers import companies as companies_mod  # noqa: E402
from jobbot.careers import resolve as resolve_mod  # noqa: E402
from jobbot.careers.resolve import slug_variants  # noqa: E402
from jobbot.http import Http  # noqa: E402

COMPANIES = ROOT / "assets" / "companies.txt"
SEED = ROOT / "assets" / "companies_seed.txt"
CACHE = ROOT / "assets" / "probe_cache.json"
UA = {"User-Agent": "Mozilla/5.0 (job-hunt careers list builder)"}

URL_SOURCES = {
    "newgrad": [
        "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
        "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
        "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/NEW_GRAD_USA.md",
        "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/NEW_GRAD_INTL.md",
        "https://raw.githubusercontent.com/vanshb03/New-Grad-2026/dev/README.md",
        "https://raw.githubusercontent.com/cvrve/New-Grad-2025/dev/README.md",
        "https://raw.githubusercontent.com/ouckah/Summer2025-Internships/dev/README.md",
        "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/README.md",
        "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README-Off-Season.md",
    ],
}
UK_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
IND_PAGE = "https://ind.nl/en/public-register-recognised-sponsors/public-register-work"
TECHISH = re.compile(r"\b(tech|technolog\w*|software|digital|data|labs?|systems|cloud|analytics|cyber|fintech|ai|apps?|games?|"
                     r"gaming|robotics|platform|computing|networks?|semiconductor|quantum|payments?|interactive|studios?|"
                     r"solutions|it|online|web|mobile|engineering|automation|intelligence|security|trading|capital)\b", re.I)
LEGAL = re.compile(r"[\s,]+(b\.?v\.?|n\.?v\.?|limited|ltd\.?|plc|llp|inc\.?|gmbh|holding|holdings|group|nederland|netherlands|"
                   r"europe|emea|uk|international|services)\s*$", re.I)
YC_URL = "https://yc-oss.github.io/api/companies/all.json"
ATSLISTS_URL = "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/{}_companies.json"
ATSLISTS = ("greenhouse", "lever", "ashby", "bamboohr", "workday")
SWE_TITLE = re.compile(r"\b(software|developer|programmer|sde|swe|back-?end|front-?end|full[- ]?stack|devops|"
                       r"site reliability|sre|platform engineer|data engineer|ml engineer|machine learning engineer|"
                       r"ai engineer|mobile engineer|android|ios engineer|cloud engineer|qa engineer|test automation|"
                       r"sdet|member of technical staff)\b", re.I)
HWW_URL = "https://raw.githubusercontent.com/poteto/hiring-without-whiteboards/main/README.md"
REMOTE_URL = "https://raw.githubusercontent.com/yanirs/established-remote/master/README.md"

# job-board links -> (ats, board)
BOARD_RE = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_(?:app|board)\?for=)?([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("personio", re.compile(r"https?://([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
    ("breezy", re.compile(r"https?://([a-z0-9-]+)\.breezy\.hr", re.I)),
    ("workday", re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I)),
]
PROBE_ATS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "breezy", "personio")
NOT_BOARDS = {"embed", "jobs", "job", "apply", "careers", "v1", "api", "search", "en-us", "login", "o"}

_local = threading.local()
_lock = threading.Lock()


def session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(UA)
    return _local.s


def fetch_text(url: str) -> str:
    try:
        r = session().get(url, timeout=60)
        return r.text if r.status_code == 200 else ""
    except requests.RequestException:
        return ""


def boards_in(text: str) -> list[tuple[str, str]]:
    out = []
    for ats, rx in BOARD_RE:
        for m in rx.finditer(text or ""):
            if ats == "workday":
                sub, dc, site = m.group(1), m.group(2), m.group(3)
                out.append((ats, f"{sub}.{dc}.myworkdayjobs.com/{sub}/{site}"))
            else:
                b = m.group(1).strip("./").lower() if ats != "ashby" else m.group(1).strip("./")
                if b and b.lower() not in NOT_BOARDS:
                    out.append((ats, b))
    return out


def check(ats: str, board: str) -> int | None:
    """Open jobs on a board, 0 for an empty but real board, None when it does not exist / answer."""
    s = session()
    try:
        if ats == "greenhouse":
            r = s.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", timeout=12)
            return len(r.json().get("jobs") or []) if r.status_code == 200 else None
        if ats == "lever":
            r = s.get(f"https://api.lever.co/v0/postings/{board}?mode=json", timeout=12)
            return len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else None
        if ats == "ashby":
            r = s.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}", timeout=12)
            return len(r.json().get("jobs") or []) if r.status_code == 200 else None
        if ats == "smartrecruiters":
            r = s.get(f"https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=1", timeout=12)
            return int(r.json().get("totalFound") or 0) if r.status_code == 200 else None
        if ats == "workable":
            r = s.get(f"https://apply.workable.com/api/v1/widget/accounts/{board}", timeout=12)
            return len(r.json().get("jobs") or []) if r.status_code == 200 else None
        if ats == "recruitee":
            r = s.get(f"https://{board}.recruitee.com/api/offers/", timeout=12)
            return len(r.json().get("offers") or []) if r.status_code == 200 else None
        if ats == "breezy":
            r = s.get(f"https://{board}.breezy.hr/json", timeout=12)
            return len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else None
        if ats == "personio":
            # unknown tenants redirect to personio.com; the feed rate-limits bursts (429)
            for wait in (0, 3, 8):
                time.sleep(wait)
                r = s.get(f"https://{board}.jobs.personio.de/xml", timeout=15, allow_redirects=False)
                if r.status_code != 429:
                    break
            return r.text.count("<position>") if r.status_code == 200 and "xml" in r.headers.get("content-type", "") else None
        if ats == "workday":
            host, tenant, site = board.split("/", 2)
            r = s.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                       timeout=15)
            return int(r.json().get("total") or 0) if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None
    return None


def swe_count(ats: str, board: str) -> tuple[int, str] | None:
    """(open software roles, company name when the board says) for a board, or None when it does not answer."""
    s = session()
    try:
        if ats == "greenhouse":
            r = s.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", timeout=15)
            if r.status_code != 200:
                return None
            jobs = r.json().get("jobs") or []
            return (sum(bool(SWE_TITLE.search(j.get("title") or "")) for j in jobs),
                    (jobs[0].get("company_name") if jobs else "") or "")
        if ats == "lever":
            r = s.get(f"https://api.lever.co/v0/postings/{board}?mode=json", timeout=15)
            d = r.json() if r.status_code == 200 else None
            return (sum(bool(SWE_TITLE.search(j.get("text") or "")) for j in d), "") if isinstance(d, list) else None
        if ats == "ashby":
            r = s.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}", timeout=15)
            if r.status_code != 200:
                return None
            return sum(bool(SWE_TITLE.search(j.get("title") or "")) for j in r.json().get("jobs") or []), ""
        if ats == "bamboohr":
            r = s.get(f"https://{board}.bamboohr.com/careers/list", headers={"Accept": "application/json"},
                      timeout=15, allow_redirects=False)
            if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                return None
            return sum(bool(SWE_TITLE.search(j.get("jobOpeningName") or "")) for j in r.json().get("result") or []), ""
        if ats == "workday":
            host, tenant, site = board.split("/", 2)
            r = s.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs", timeout=20,
                       json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "software engineer"})
            if r.status_code != 200:
                return None
            posts = r.json().get("jobPostings") or []
            return sum(bool(SWE_TITLE.search(p.get("title") or "")) for p in posts), ""
    except (requests.RequestException, ValueError):
        return None
    return None


def slug_name(slug: str) -> str:
    """'10up-2' -> '10up', 'acme_labs' -> 'Acme Labs' (the lists carry slugs, not names)."""
    slug = re.sub(r"[-_]\d{1,2}$", "", slug)
    words = re.split(r"[-_.]+", slug)
    return " ".join(w if any(ch.isdigit() for ch in w) else w.capitalize() for w in words if w)


def src_atslists():
    """(ats, board, fallback name) for every board in the aggregator's per-ATS lists."""
    out = []
    for ats in ATSLISTS:
        try:
            rows = json.loads(fetch_text(ATSLISTS_URL.format(ats)) or "[]")
        except ValueError:
            continue
        for slug in rows:
            if not isinstance(slug, str) or not slug.strip("-"):
                continue
            if ats == "workday":
                parts = slug.split("|")
                if len(parts) != 3:
                    continue
                tenant, wd, site = parts
                out.append((ats, f"{tenant}.{wd}.myworkdayjobs.com/{tenant}/{site}", slug_name(tenant)))
            else:
                out.append((ats, slug, slug_name(slug)))
    return out


def probe_name(name: str, url: str | None, strict: bool = False, only=PROBE_ATS) -> tuple[str, str, int] | None:
    """Guess a board from a company name: the first variant with open jobs on any board.
    strict (register names like "Cloud Solutions Ltd"): only the whole-name slugs, 5+ characters,
    so a generic first word ("cloud") cannot pick up somebody else's board."""
    variants = slug_variants(name, url)
    if strict:
        variants = [v for v in variants[:2] if len(v) >= 5]
    for slug in variants[:5]:
        for ats in only:
            n = check(ats, slug)
            if n and not foreign(name, ats, slug):
                return ats, slug, n
    return None


# Breezy and Personio tenants are plain words ("teleport", "feather"), so a name guess often lands
# on somebody else's board (35 of the first 270 did). Those boards name their company: a board
# that names a different one is not taken. A board that names nobody is kept.
OWNER_CHECKED = ("breezy", "personio")
_owner_http = Http(min_interval=0.6)


def foreign(name: str, ats: str, board: str) -> bool:
    if ats not in OWNER_CHECKED:
        return False
    return resolve_mod.same_company(name, resolve_mod.owner(_owner_http, ats, board)) is False


def clean_name(s: str) -> str:
    s = re.sub(r"<[^>]+>|\*\*|__|\[|\]\([^)]*\)|[\[\]]|[\u200b-\u200f\ufeff]", " ", s or "")
    s = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", s)
    return re.sub(r"\s+", " ", s).strip(" |↳-–")[:60]


# ------------------------------------------------------------------ sources
def src_newgrad():
    """(name, ats, board, tag) from new-grad / internship lists (links name the board)."""
    out = []
    for url in URL_SOURCES["newgrad"]:
        text = fetch_text(url)
        if not text:
            continue
        if url.endswith(".json"):
            try:
                for row in json.loads(text):
                    for ats, board in boards_in(row.get("url") or ""):
                        out.append((clean_name(row.get("company_name")), ats, board, "new-grad / 0-2 YOE list"))
            except ValueError:
                pass
            continue
        last = ""
        for line in text.splitlines():
            cells = [c for c in re.split(r"\s*\|\s*|</?td>", line) if c.strip()]
            if cells:
                first = clean_name(cells[0])
                if first and first not in ("↳", "Company"):
                    last = first
            for ats, board in boards_in(line):
                out.append((last or board, ats, board, "new-grad / 0-2 YOE list"))
    return out


def src_runs():
    out = []
    for path in glob.glob(str(Path.home() / "Documents" / "JobHunt" / "*" / "jobs.json")):
        try:
            for j in json.loads(Path(path).read_text(encoding="utf-8")):
                for ats, board in boards_in(j.get("url") or ""):
                    out.append((clean_name(j.get("company") or board), ats, board, "seen in your job-hunt runs"))
        except (OSError, ValueError):
            continue
    return out


def src_yc():
    try:
        data = json.loads(fetch_text(YC_URL) or "[]")
    except ValueError:
        return []
    out = []
    for c in data:
        if (c.get("status") or "").lower() != "active":
            continue
        if not (c.get("isHiring") or (c.get("team_size") or 0) >= 25):
            continue
        regions = ", ".join((c.get("regions") or [])[:3])
        tag = " · ".join(t for t in (f"YC {c.get('batch') or ''}".strip(), regions,
                                      "hiring" if c.get("isHiring") else "") if t)
        out.append((clean_name(c.get("name")), c.get("website") or "", tag, [c.get("slug") or ""]))
    return out


def src_markdown_names(url: str, tag: str):
    out = []
    for line in fetch_text(url).splitlines():
        m = re.match(r"\s*[-*]\s*\[([^\]]+)\]\((https?://[^)\s]+)\)", line) or re.match(r"\s*\|\s*\[([^\]]+)\]\((https?://[^)\s]+)\)", line)
        if m:
            out.append((clean_name(m.group(1)), m.group(2), tag, []))
    return out


def _legal_strip(name: str) -> str:
    prev = None
    name = re.sub(r'^"+|"+$', "", (name or "").replace('""', '"')).strip()
    while prev != name:
        prev, name = name, LEGAL.sub("", name).strip()
    return name


def src_uk():
    """UK Home Office register of licensed sponsors (Skilled Worker), tech-sounding names only."""
    import csv
    import io
    m = re.search(r'https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv', fetch_text(UK_PAGE))
    if not m:
        return []
    try:
        raw = session().get(m.group(0), timeout=120).content.decode("utf-8", "ignore")
    except requests.RequestException:
        return []
    names = {}
    for r in csv.DictReader(io.StringIO(raw)):
        n = (r.get("Organisation Name") or "").strip()
        if "Skilled Worker" in (r.get("Route") or "") and TECHISH.search(n):
            names.setdefault(_legal_strip(n), (r.get("Town/City") or "").strip())
    return [(n, "", f"UK visa sponsor (Skilled Worker){' · ' + t if t else ''}", []) for n, t in names.items() if n]


def src_ind():
    """Netherlands IND public register of recognised sponsors (highly-skilled migrant visa)."""
    names = {_legal_strip(n) for n in re.findall(r'<th scope="row">([^<]+)</th>', fetch_text(IND_PAGE))}
    return [(n, "", "NL recognised sponsor (highly-skilled migrant visa)", []) for n in names if n and len(n) > 1]


def src_seed():
    out = []
    for line in SEED.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, _, tag = (p.strip() for p in line.partition("|"))
        out.append((name, "", tag, []))
    return out


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default="newgrad,runs,seed,hww,remote,yc,ind,uk,atslists")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    want = set(a.sources.split(","))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    existing = companies_mod.load(str(COMPANIES))
    have_names = {re.sub(r"[^a-z0-9]", "", c.name.lower()) for c in existing}
    have_boards = {(c.ats, (c.board or "").lower()) for c in existing}
    found: dict[str, tuple[str, str, str, str, int]] = {}      # key(name) -> (name, ats, board, tag, jobs)

    def add(name, ats, board, tag, n):
        key = re.sub(r"[^a-z0-9]", "", (name or board).lower())
        if not key or key in have_names or (ats, board.lower()) in have_boards:
            return
        with _lock:
            prev = found.get(key)
            if prev is None or n > prev[4]:
                found[key] = (name or board, ats, board, tag, n)

    t0 = time.time()
    # 1. links that name the board: verify each distinct board once
    linked = []
    if "newgrad" in want:
        linked += src_newgrad()
    if "runs" in want:
        linked += src_runs()
    distinct = {}
    for name, ats, board, tag in linked:
        distinct.setdefault((ats, board), (name, tag))
    print(f"board links: {len(linked)} ({len(distinct)} distinct boards)", flush=True)

    def verify(item):
        (ats, board), (name, tag) = item
        k = f"{ats}:{board.lower()}"
        n = cache.get(k)
        if k not in cache:
            n = check(ats, board)
            with _lock:
                cache[k] = n
        if n is not None:
            add(name, ats, board, tag, n)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(verify, distinct.items()))
    print(f"  verified so far: {len(found)} new companies ({time.time() - t0:.0f}s)", flush=True)

    # 2. names: guess the board and require open jobs
    named = []
    if "seed" in want:
        named += src_seed()
    if "hww" in want:
        named += src_markdown_names(HWW_URL, "hiring-without-whiteboards")
    if "remote" in want:
        named += src_markdown_names(REMOTE_URL, "remote-first")
    if "yc" in want:
        named += src_yc()
    if "ind" in want:
        named += src_ind()
    if "uk" in want:
        named += src_uk()
    named = [x for x in named if x[0] and re.sub(r"[^a-z0-9]", "", x[0].lower()) not in have_names]
    print(f"names to probe: {len(named)}", flush=True)

    def guess(item):
        name, url, tag, _extra = item
        k = "name:" + name.lower()
        hit = cache.get(k)
        if k not in cache:
            r = probe_name(name, url or None, strict="sponsor" in tag)
            hit = list(r) if r else None
            with _lock:
                cache[k] = hit
                cache["v2:" + k] = True
        elif hit is None and ("v2:" + k) not in cache:       # missed before Breezy/Personio were probed
            r = probe_name(name, url or None, strict="sponsor" in tag, only=("breezy", "personio"))
            hit = list(r) if r else None
            with _lock:
                cache[k] = hit
                cache["v2:" + k] = True
        if hit and hit[0] in OWNER_CHECKED and ("own:" + k) not in cache:   # cached before the owner check
            ok = not foreign(name, hit[0], hit[1])
            with _lock:
                cache["own:" + k] = True
                if not ok:
                    cache[k] = hit = None
        if hit:
            add(name, hit[0], hit[1], tag, hit[2])

    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for _ in as_completed([ex.submit(guess, x) for x in named]):
            done += 1
            if done % 250 == 0:
                print(f"  probed {done}/{len(named)} names, {len(found)} new companies ({time.time() - t0:.0f}s)", flush=True)
                CACHE.write_text(json.dumps(cache), encoding="utf-8")
    CACHE.write_text(json.dumps(cache), encoding="utf-8")

    # 3. whole-ATS lists: keep boards that have software roles open today
    if "atslists" in want:
        boards = [b for b in src_atslists() if (b[0], b[1].lower()) not in have_boards]
        print(f"ATS-list boards to check: {len(boards)}", flush=True)

        def swe(item):
            ats, board, fallback = item
            k = f"swe:{ats}:{board.lower()}"
            hit = cache.get(k)
            if k not in cache:
                r = swe_count(ats, board)
                hit = list(r) if r else None
                with _lock:
                    cache[k] = hit
            if hit and hit[0] > 0:
                add(clean_name(hit[1]) or fallback, ats, board, f"public {ats} list · {hit[0]} software role(s) open", hit[0])

        done = 0
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for _ in as_completed([ex.submit(swe, x) for x in boards]):
                done += 1
                if done % 1000 == 0:
                    print(f"  checked {done}/{len(boards)} boards, {len(found)} new companies ({time.time() - t0:.0f}s)",
                          flush=True)
                    CACHE.write_text(json.dumps(cache), encoding="utf-8")
        CACHE.write_text(json.dumps(cache), encoding="utf-8")

    rows = sorted(found.values(), key=lambda r: r[0].lower())
    print(f"new verified companies: {len(rows)} (total would be {len(existing) + len(rows)}) in {time.time() - t0:.0f}s", flush=True)
    if a.dry_run or not rows:
        return 0
    width = max(len(r[0]) for r in rows)
    lines = ["", f"# ---- discovered by build_companies.py on {time.strftime('%Y-%m-%d')} (every board verified live)"]
    for name, ats, board, tag, n in rows:
        name = name.replace("|", "/")
        tail = " when added" if tag.endswith("open") else f"{' · ' if tag else ''}{n} open job(s) when added"
        lines.append(f"{name:<{width}} | {ats:<15} | {board} | {tag}{tail}")
    with COMPANIES.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"appended {len(rows)} rows to {COMPANIES}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
