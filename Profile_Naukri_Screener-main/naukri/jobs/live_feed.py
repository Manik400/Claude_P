"""The live feed: new LinkedIn job postings within minutes of being posted, plus the hiring posts the
watchers found, newest first, for the phone's Live tab.

    python -m naukri.jobs.live_feed --loop       run all day (what the scheduled task LiveFeed does)
    python -m naukri.jobs.live_feed --once       one tick now, then publish
    python -m naukri.jobs.live_feed --status     what the feed holds

How it stays live without risking your LinkedIn account:

  * Jobs come from LinkedIn's PUBLIC guest job search (linkedin.com/jobs-guest/...), the one
    the logged-out jobs page uses. No session, no cookies, nothing tied to your account, so
    checking it every minute or two cannot restrict you. Each tick asks one "hot" query
    (software engineer / developer, India and remote, newest first, last 30 minutes) and one
    query from a rotation of roles x places (last hour), and fetches the detail page (seniority,
    employment type, applicants, years asked) of a few new software postings.
  * LinkedIn answers too-fast clients with HTTP 429; the interval then doubles (up to 15
    minutes) and comes back down as answers return to normal.
  * Hiring POSTS (LinkedIn, X, Telegram, Reddit, HN, Mastodon) are read from the stores the
    posts watchers keep, so a post appears here as soon as a watcher has read it. Posts the
    rules are unsure about are checked once by the local model (hiring post? software role?
    years asked?), cached by id. No model is close to 100% right; this only cuts mistakes.

The feed (last FEED_HOURS, newest first) is published to the `live` branch as feed.json through
the GitHub API as a single commit that replaces the previous one: no Pages rebuild, no history
growth, and the phone reads it seconds after it is written. Local copy: data/live/feed.json.
Log: logs/live_feed.log. One instance at a time (data/live/live.lock); the task restarts it
after a reboot or if it stops, and it restarts itself when the code changes.
"""
from __future__ import annotations

import argparse
import base64
import html as html_mod
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import linkedin_posts as lp

log = logging.getLogger("naukri.jobs.live_feed")

ROOT = Path(__file__).resolve().parent.parent.parent
DIR = ROOT / "data" / "live"
FEED_PATH = DIR / "feed.json"
LOCK_PATH = DIR / "live.lock"
AI_CACHE_PATH = DIR / "ai_cache.json"
LOG_PATH = ROOT / "logs" / "live_feed.log"
BRANCH = "live"
PUBLISH_NAME = "feed.json"

FEED_HOURS = 48
MAX_ITEMS = 1500
BASE_INTERVAL = 90           # seconds between ticks when LinkedIn answers normally
MAX_INTERVAL = 900
DETAILS_PER_TICK = 4
MAX_PAGES = 4                # pages of 10 a search may read in one tick when every posting on them is new
AI_PER_TICK = 2               # local-model checks per tick; a tick never waits long on the model
PUBLISH_MIN_GAP = 45         # seconds; never publish more often than this

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

HOT = [("software engineer", "India", None), ("software developer", "India", None), ("software engineer", "Worldwide", "2")]
ROLES = ["software engineer", "software developer", "SDE", "backend developer", "java developer", "full stack developer",
         "python developer", "frontend developer", "SWE", "backend engineer"]
PLACES = [("India", None), ("India", "2"), ("Worldwide", "2"), ("Germany", None), ("Netherlands", None), ("United Arab Emirates", None),
          ("Singapore", None), ("United Kingdom", None), ("Ireland", None), ("Canada", None)]

SOFTWARE_RX = re.compile(r"\b(software|developer|engineer|sde|swe|programmer|backend|back-end|front-?end|full[- ]?stack|java|python|"
                         r"\.net|dotnet|node|react|angular|golang|devops|sre|platform|mobile|android|ios|flutter|qa|sdet|data engineer)\b", re.I)
NON_SOFTWARE_RX = re.compile(r"\b(sales|marketing|civil|mechanical|electrical engineer|chemical|hr\b|recruiter|accountant|nurse|teacher|"
                             r"driver|customer support|business development)\b", re.I)
AGO_RX = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month)s?\s+ago|just now", re.I)


# ----------------------------------------------------------------------------- reading LinkedIn's guest pages

def _get(url: str, params: dict | None = None, timeout: int = 25):
    import requests
    return requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def _txt(s: str | None) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def age_hours(text: str) -> float | None:
    m = AGO_RX.search(text or "")
    if not m:
        return None
    if not m.group(1):
        return 0.0
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * {"second": 1 / 3600, "minute": 1 / 60, "hour": 1, "day": 24, "week": 168, "month": 720}[unit]


def parse_search(html: str, now: datetime, workplace: str = "") -> list[dict]:
    """Job cards from one guest search page."""
    out = []
    for card in (html or "").split("<li>")[1:]:
        jid = re.search(r"jobPosting:(\d+)", card)
        if not jid:
            continue
        title = _txt((re.search(r'base-search-card__title">(.*?)</h3>', card, re.S) or [None, ""])[1])
        company = _txt((re.search(r'base-search-card__subtitle">(.*?)</h4>', card, re.S) or [None, ""])[1])
        loc = _txt((re.search(r'job-search-card__location">(.*?)</span>', card, re.S) or [None, ""])[1])
        tm = re.search(r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>', card, re.S)
        ago = _txt(tm.group(2)) if tm else ""
        h = age_hours(ago)
        posted = now - timedelta(hours=h) if h is not None else None
        if posted is None and tm:
            try:
                posted = datetime.fromisoformat(tm.group(1)).replace(tzinfo=timezone.utc)
            except ValueError:
                posted = None
        link = re.search(r'href="(https://[a-z]+\.linkedin\.com/jobs/view/[^"?]+)', card)
        wp = workplace or ("remote" if re.search(r"\bremote\b", loc, re.I) else "hybrid" if re.search(r"\bhybrid\b", loc, re.I) else "")
        out.append({"id": "li:" + jid.group(1), "job_id": jid.group(1), "kind": "job", "platform": "linkedin", "title": title,
                    "company": company, "location": loc, "workplace": wp, "age_text": ago,
                    "posted_at": posted.isoformat(timespec="seconds") if posted else None,
                    "url": f"https://www.linkedin.com/jobs/view/{jid.group(1)}/" if not link else link.group(1).replace("in.linkedin.com", "www.linkedin.com"),
                    "easy_apply": "easy apply" in card.lower()})
    return out


def parse_detail(html: str) -> dict:
    crit = {k.strip().lower(): _txt(v) for k, v in re.findall(
        r'description__job-criteria-subheader">\s*(.*?)\s*</h3>.*?description__job-criteria-text[^>]*>(.*?)</span>', html or "", re.S)}
    desc = _txt((re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', html or "", re.S) or [None, ""])[1])
    apps = _txt((re.search(r'num-applicants__caption[^>]*>(.*?)<', html or "", re.S) or [None, ""])[1])
    n = re.search(r"(\d[\d,]*)", apps)
    from .linkedin_premium import years_asked, sponsorship_of
    out = {"seniority": crit.get("seniority level", ""), "employment": crit.get("employment type", ""),
           "function": crit.get("job function", ""), "applicants": int(n.group(1).replace(",", "")) if n else None,
           "applicants_text": apps, "years_min": years_asked(desc), "snippet": desc[:300], "detailed": True}
    if desc:
        sp = sponsorship_of("", desc)
        out["visa"], out["relocation"] = sp.get("visa", "unclear"), sp.get("relocation", "unclear")
    if re.search(r"\b(remote|work from home|wfh)\b", desc[:2000], re.I) and not out.get("workplace"):
        out["remote_hint"] = True
    return out


def search(keywords: str, location: str, wt: str | None, seconds: int, now: datetime, start: int = 0) -> tuple[list[dict], int]:
    params = {"keywords": keywords, "location": location, "f_TPR": f"r{seconds}", "sortBy": "DD", "start": start}
    if wt:
        params["f_WT"] = wt
    r = _get(GUEST_SEARCH, params)
    if r.status_code != 200:
        return [], r.status_code
    return parse_search(r.text, now, "remote" if wt == "2" else ""), 200


# ----------------------------------------------------------------------------- the local model's second opinion on posts

def _ai():
    scripts = ROOT.parent / "job-hunt" / "scripts"
    if scripts.is_dir() and str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from jobbot import localai  # type: ignore
        return localai if localai.available("llm") and localai.budget_left() > 5 else None
    except Exception:  # noqa: BLE001
        return None


def unsure(post: dict) -> bool:
    """Posts the rules may have wrong: a weak score, only a generic role, or seeker and hiring words together."""
    return (post.get("score") or 0) < 70 or post.get("roles") == ["software (general)"] or bool(post.get("seeker") and post.get("hiring"))


def ai_check(post: dict) -> dict | None:
    ai = _ai()
    if ai is None:
        return None
    text = (post.get("text") or "")[:1800]
    try:
        out = ai.ask("POST:\n" + text + "\n\nAUTHOR HEADLINE: " + (post.get("headline") or "") +
                     "\n\nIs this a post by someone HIRING (not a person looking for a job, not a news item)? Is the role a software / IT "
                     "engineering role? What is the minimum years of experience it asks for (-1 if not stated)?",
                     system="You classify job-related social media posts. Reply with JSON only.", max_tokens=60, json=True, temperature=0.0, timeout=60,
                     schema={"type": "object", "properties": {"hiring": {"type": "boolean"}, "software": {"type": "boolean"},
                                                              "min_years": {"type": "integer"}, "confidence": {"type": "number"}},
                             "required": ["hiring", "software", "confidence"]})
    except Exception as exc:  # noqa: BLE001
        log.debug("ai check failed: %s", exc)
        return None
    if not isinstance(out, dict) or "hiring" not in out:
        return None
    years = out.get("min_years")
    years = years if isinstance(years, int) and 0 <= years <= 30 else None
    return {"hiring": bool(out.get("hiring")), "software": bool(out.get("software")), "min_years": years,
            "confidence": float(out.get("confidence") or 0)}


# ----------------------------------------------------------------------------- the feed

def load(path: Path = FEED_PATH) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("items"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"items": [], "cursor": 0, "hot": 0, "pc": {}}


def save(feed: dict, path: Path = FEED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _sort_key(it: dict):
    # newest first: the posting time, then LinkedIn's job id (ids only grow), then when we first saw it
    jid = int(it.get("job_id") or 0)
    return (it.get("posted_at") or it.get("first_seen") or "", jid, it.get("first_seen") or "")


def merge_jobs(feed: dict, jobs: list[dict], now: datetime) -> list[dict]:
    """Add new postings; keep the earliest posting-time estimate for known ones. Returns the new ones."""
    by_id = {it["id"]: it for it in feed["items"]}
    new = []
    for j in jobs:
        if NON_SOFTWARE_RX.search(j.get("title") or "") or not SOFTWARE_RX.search(j.get("title") or ""):
            continue
        old = by_id.get(j["id"])
        if old is None:
            j["first_seen"] = now.isoformat(timespec="seconds")
            by_id[j["id"]] = j
            feed["items"].append(j)
            new.append(j)
        else:
            if j.get("posted_at") and (not old.get("posted_at") or j["posted_at"] < old["posted_at"]):
                old["posted_at"] = j["posted_at"]
            if j.get("workplace") and not old.get("workplace"):
                old["workplace"] = j["workplace"]
    return new


def merge_posts(feed: dict, now: datetime, ai_budget: int = AI_PER_TICK) -> int:
    """Hiring posts from the watchers' stores, newer than FEED_HOURS, judged again by the rules and,
    when unsure, once by the local model. Returns how many were added."""
    cache = {}
    try:
        cache = json.loads(AI_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    have = {it["id"] for it in feed["items"]}
    cutoff = now - timedelta(hours=FEED_HOURS)
    added = asked = 0
    model_on = None
    for path, platform in ((ROOT / "data" / "posts" / "linkedin_posts.json", "linkedin"), (ROOT / "data" / "posts" / "social_posts.json", None)):
        try:
            store = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in store.get("posts") or []:
            pid = "post:" + str(p.get("id"))
            if pid in have or not p.get("text"):
                continue
            at = lp._parse_iso(p.get("posted_at")) or lp._parse_iso(p.get("first_seen"))
            if at is None or at < cutoff:
                continue
            info = lp.classify(p["text"], p.get("headline") or "", open_to_work=bool(p.get("open_to_work")))
            if not (info.get("hiring") and info.get("roles") and not info.get("off_field")):
                continue
            verdict = cache.get(pid)
            if verdict is None and unsure(dict(p, **info)):
                if asked < ai_budget:
                    asked += 1
                    verdict = ai_check(dict(p, **info))
                    if verdict is not None:
                        cache[pid] = verdict
                    elif model_on is None:
                        model_on = _ai() is not None
                if verdict is None:
                    if model_on is None:
                        model_on = _ai() is not None
                    if model_on:
                        continue             # waits for its check on a later tick (a few a tick, so jobs never wait)
            if verdict and verdict.get("confidence", 0) >= 0.7 and not (verdict["hiring"] and verdict["software"]):
                continue                     # the model is fairly sure the rules were wrong
            if info.get("seeker"):
                continue                     # the model may only remove posts, never bring back one the rules rejected
                                             # (tested: it calls "please refer me #opentowork" a hiring post)
            exp = info.get("exp") or {}
            feed["items"].append({
                "id": pid, "kind": "post", "platform": p.get("platform") or platform or "post", "title": ", ".join(info.get("roles") or [])[:120],
                "company": p.get("author") or "", "location": ", ".join(info.get("locations") or [])[:120],
                "workplace": "remote" if re.search(r"\bremote\b|work from home|\bwfh\b", p["text"], re.I) else "",
                "posted_at": at.isoformat(timespec="seconds"), "first_seen": p.get("first_seen") or now.isoformat(timespec="seconds"),
                "url": p.get("url") or p.get("author_url") or "", "years_min": exp.get("min") if exp.get("min") is not None else (verdict or {}).get("min_years"),
                "entry": bool(exp.get("entry")), "snippet": p["text"][:400], "emails": (info.get("emails") or [])[:3], "links": (p.get("links") or [])[:3],
                "headline": (p.get("headline") or "")[:140], "ai": verdict})
            have.add(pid)
            added += 1
    if asked:
        AI_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        AI_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return added


def prune(feed: dict, now: datetime) -> None:
    cutoff = (now - timedelta(hours=FEED_HOURS)).isoformat(timespec="seconds")
    items = [it for it in feed["items"] if (it.get("posted_at") or it.get("first_seen") or "") >= cutoff]
    items.sort(key=_sort_key, reverse=True)
    feed["items"] = items[:MAX_ITEMS]


# ----------------------------------------------------------------------------- publishing to the `live` branch

def _gh(args: list[str], body: dict | None = None) -> dict:
    sys.path.insert(0, str(ROOT.parent / "site" / "tools"))
    import pages_git  # type: ignore
    r = subprocess.run([pages_git.gh_exe(), "api"] + args + (["--input", "-"] if body is not None else []),
                       input=json.dumps(body) if body is not None else None, text=True, encoding="utf-8", errors="replace",
                       capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])
    return json.loads(r.stdout or "{}")


def _slug() -> str:
    sys.path.insert(0, str(ROOT.parent / "site" / "tools"))
    import pages_git  # type: ignore
    repo_url = None
    try:
        from phone_publish import load_config  # type: ignore
        repo_url = (load_config() or {}).get("repo_url")
    except (SystemExit, Exception):  # noqa: BLE001
        repo_url = None
    return pages_git.repo_slug(repo_url or pages_git.default_repo_url())


def publish(feed: dict) -> bool:
    """feed.json as the only file of a single, parentless commit on `live` (force-updated)."""
    payload = {"updated": feed.get("updated"), "pc": feed.get("pc") or {}, "hours": FEED_HOURS,
               "items": feed["items"]}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        slug = _slug()
        blob = _gh(["-X", "POST", f"repos/{slug}/git/blobs"], {"content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "encoding": "base64"})
        tree = _gh(["-X", "POST", f"repos/{slug}/git/trees"], {"tree": [{"path": PUBLISH_NAME, "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
        commit = _gh(["-X", "POST", f"repos/{slug}/git/commits"], {"message": f"live feed: {len(feed['items'])} item(s)", "tree": tree["sha"]})
        try:
            _gh(["-X", "PATCH", f"repos/{slug}/git/refs/heads/{BRANCH}"], {"sha": commit["sha"], "force": True})
        except RuntimeError:
            _gh(["-X", "POST", f"repos/{slug}/git/refs"], {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("publish failed: %s", str(exc)[:300])
        return False


# ----------------------------------------------------------------------------- a tick, and the loop

def tick(feed: dict, now: datetime | None = None) -> dict:
    """One round: the hot query, one rotation query, a few detail pages, the posts. Returns stats."""
    now = now or datetime.now(timezone.utc)
    stats = {"new_jobs": 0, "new_posts": 0, "details": 0, "status": 200, "queries": []}
    hot = HOT[int(feed.get("hot") or 0) % len(HOT)]
    feed["hot"] = int(feed.get("hot") or 0) + 1
    combos = [(r, p, wt) for p, wt in PLACES for r in ROLES]
    rot = combos[int(feed.get("cursor") or 0) % len(combos)]
    feed["cursor"] = int(feed.get("cursor") or 0) + 1
    # Each search looks back to the last time it ran (plus a margin), so a rotation that comes round
    # every few hours still sees every posting in between; a page that is all new is followed by the next.
    last = feed.setdefault("last_checked", {})
    for kw, loc, wt, floor in ((hot[0], hot[1], hot[2], 1800), (rot[0], rot[1], rot[2], 3600)):
        key = f"{kw}|{loc}|{wt or ''}"
        prev = lp._parse_iso(last.get(key))
        secs = int(min(86400, max(floor, (now - prev).total_seconds() + 300 if prev else floor)))
        got, status, page = 0, 200, 0
        new: list[dict] = []
        while page < MAX_PAGES:
            jobs, status = search(kw, loc, wt, secs, now, start=page * 10)
            if status != 200:
                break
            fresh = merge_jobs(feed, jobs, now)
            new += fresh
            got += len(jobs)
            page += 1
            if len(jobs) < 10 or len(fresh) < 8:
                break               # reached postings we already have, or the end of the results
            time.sleep(random.uniform(1.5, 3.5))
        stats["queries"].append(f"{kw} / {loc}{' remote' if wt == '2' else ''} ({secs // 60} min, {page} page{'s' if page != 1 else ''}): "
                                f"{got if status == 200 else status}")
        stats["new_jobs"] += len(new)
        if status != 200:
            stats["status"] = status
            if status == 429:
                break
            continue
        last[key] = now.isoformat(timespec="seconds")
        time.sleep(random.uniform(2, 5))
    if stats["status"] != 429:
        pending = [it for it in feed["items"] if it.get("kind") == "job" and not it.get("detailed")]
        pending.sort(key=_sort_key, reverse=True)
        for it in pending[:DETAILS_PER_TICK]:
            r = _get(GUEST_DETAIL + it["job_id"])
            if r.status_code == 429:
                stats["status"] = 429
                break
            if r.status_code == 200:
                it.update(parse_detail(r.text))
                if it.pop("remote_hint", False) and not it.get("workplace"):
                    it["workplace"] = "remote?"
                stats["details"] += 1
            else:
                it["detailed"] = "failed"
            time.sleep(random.uniform(1.5, 3.5))
    stats["new_posts"] = merge_posts(feed, now)
    prune(feed, now)
    return stats


def single_instance() -> bool:
    """True when no other live-feed process holds the lock (a stale lock from a dead process is taken over)."""
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        pid = int(LOCK_PATH.read_text().strip() or 0)
    except (OSError, ValueError):
        pid = 0
    if pid and pid != os.getpid() and _alive(pid):
        return False
    LOCK_PATH.write_text(str(os.getpid()))
    return True


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                    # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def loop() -> int:
    if not single_instance():
        log.info("another live-feed process is running - this one exits (no duplicates)")
        return 0
    stamp = lp.code_stamp()
    feed = load()
    interval = BASE_INTERVAL
    last_pub = 0.0
    log.info("live feed: a tick every %ds (up to %ds when LinkedIn slows us down), last %dh kept", BASE_INTERVAL, MAX_INTERVAL, FEED_HOURS)
    while True:
        if lp.code_changed(stamp):
            log.info("the code changed - exiting so Task Scheduler restarts it on the new code")
            return 0
        started = time.time()
        now = datetime.now(timezone.utc)
        try:
            st = tick(feed, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("tick failed: %s", exc)
            st = {"new_jobs": 0, "new_posts": 0, "details": 0, "status": 0, "queries": [], "error": str(exc)[:200]}
        interval = min(MAX_INTERVAL, interval * 2) if st.get("status") == 429 else max(BASE_INTERVAL, int(interval * 0.75))
        pc = feed.setdefault("pc", {})
        pc.update({"host": os.environ.get("COMPUTERNAME", ""), "last_tick": now.isoformat(timespec="seconds"), "ticks": int(pc.get("ticks") or 0) + 1,
                   "interval_s": interval, "last_status": st.get("status"), "last_queries": st.get("queries"), "last_error": st.get("error", "")})
        feed["updated"] = now.isoformat(timespec="seconds")
        save(feed)
        changed = st["new_jobs"] or st["new_posts"] or st["details"]
        if changed or time.time() - last_pub > 600:            # new items, or a heartbeat every 10 minutes
            if time.time() - last_pub >= PUBLISH_MIN_GAP and publish(feed):
                last_pub = time.time()
        log.info("tick: +%d job(s), +%d post(s), %d detail(s), %d in feed%s; next in %ds%s", st["new_jobs"], st["new_posts"], st["details"],
                 len(feed["items"]), " (LinkedIn said 429: slowing down)" if st.get("status") == 429 else "", interval,
                 " · " + "; ".join(st["queries"]) if st["queries"] else "")
        lp.nap(max(20, interval - (time.time() - started) + random.uniform(-10, 10)), stamp, check_every=30)


def _setup_logging(verbose: bool) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", handlers=handlers)
    for noisy in ("urllib3", "naukri.jobs.linkedin_posts", "jobbot.localai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--loop", action="store_true")
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--status", action="store_true")
    ap.add_argument("--no-publish", action="store_true", dest="no_publish")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    _setup_logging(args.verbose)
    if args.status:
        f = load()
        jobs = [i for i in f["items"] if i.get("kind") == "job"]
        print(f"\n  {len(f['items'])} item(s): {len(jobs)} job(s), {len(f['items']) - len(jobs)} post(s); updated {f.get('updated')}\n")
        for it in f["items"][:15]:
            print(f"  {(it.get('posted_at') or '')[:16]}  {it.get('kind'):<4} {(it.get('title') or '')[:42]:<42} {(it.get('company') or '')[:22]:<22} {(it.get('location') or '')[:26]}")
        return 0
    if args.loop:
        lp._guard_children()
        lp._keep_awake()
        return loop()
    feed = load()
    st = tick(feed)
    feed["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(feed)
    ok = publish(feed) if not args.no_publish else False
    print(f"\n  +{st['new_jobs']} job(s), +{st['new_posts']} post(s), {st['details']} detail(s); {len(feed['items'])} in the feed; "
          f"published: {ok}. {'; '.join(st['queries'])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
