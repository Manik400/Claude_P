"""Hiring posts everywhere else: X (Twitter), Telegram channels, Reddit, Hacker News "Who is hiring",
Mastodon and Bluesky - the same idea as the LinkedIn hiring-posts watcher, for the other places
recruiters post "we are hiring".

    python -m naukri.jobs.social_posts --once                one pass over every source, then publish
    python -m naukri.jobs.social_posts --loop                the same every 30 min, for as long as the PC is on
    python -m naukri.jobs.social_posts --once --source telegram,reddit     only these sources
    python -m naukri.jobs.social_posts --login-x             sign in to X once (saved to data/x_state.json)
    python -m naukri.jobs.social_posts --once --show         X read in a visible browser

Sources (data/posts/social.yaml turns each on/off and sets its channels / queries; social.example.yaml):

  telegram   public channels, read from t.me/s/<channel> (no account needed): one page per channel,
             the last ~20 messages, exact timestamps.
  reddit     subreddits' newest posts through their public RSS (no account): r/forhire, r/hiring,
             r/developersIndia ... titles + bodies, exact timestamps.
  hn         the current month's "Ask HN: Who is hiring?" thread through the Algolia API: every new
             comment is one job post (company, location, REMOTE/ONSITE, stack), exact timestamps.
  mastodon   public hashtag timelines (#hiring, #hiringnow, #techjobs) on mastodon.social, no account.
  bluesky    the public search API, newest first. Some networks answer 403 - then it is skipped.
  x          X's own search, "Latest" tab, through a saved browser session (--login-x once). Read
             headless like LinkedIn; without the session the source is skipped with one log line.

Every post goes through the LinkedIn watcher's reader (linkedin_posts.classify): is it a hiring post
and not a job seeker's, which software roles, what experience, the emails, links, skills, places,
batch years and pay. The ones that are a hiring post for a software role fitting 0-2 years, from the
last WINDOW_HOURS, are published to the phone's Posts tab as data/posts/social_posts.json (each
with its `platform`), next to the LinkedIn file. Local store: data/posts/social_posts.json (a week).
Log: logs/social_posts.log. Everything here only READS.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import logging
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import linkedin_posts as lp

log = logging.getLogger("naukri.jobs.social_posts")

ROOT = Path(__file__).resolve().parent.parent.parent
STORE_PATH = ROOT / "data" / "posts" / "social_posts.json"
CONFIG_PATH = ROOT / "data" / "posts" / "social.yaml"
X_STATE_PATH = ROOT / "data" / "x_state.json"
LOG_PATH = ROOT / "logs" / "social_posts.log"
PUBLISH_PATH = "data/posts/social_posts.json"

WINDOW_HOURS = 12
KEEP_HOURS = 7 * 24
EVERY_MINUTES = 30
MAX_PUBLISHED = 500
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

DEFAULTS: dict = {
    "telegram": {"on": True, "channels": [
        "offcampusjobs4u", "jobs_and_internships_updates", "freshersjobsupdates", "remotejobss", "gocareers",
        "jobs_internships", "itjobs", "developerjobs", "TechJobsAlerts", "internfreak", "offcampus_jobs_updates",
        "jobs_for_freshers", "fresher_jobs_updates"]},
    "reddit": {"on": True, "subreddits": ["forhire", "hiring", "developersIndia", "jobbit", "techjobs", "RemoteJobs", "remotejs"]},
    "hn": {"on": True},
    "mastodon": {"on": True, "instance": "mastodon.social", "tags": ["hiring", "hiringnow", "techjobs", "jobs"]},
    "bluesky": {"on": False, "queries": ["hiring software engineer", "hiring backend engineer", "hiring developer remote"]},
    "x": {"on": True, "per_pass": 4, "queries": [
        "hiring software engineer", "we are hiring SDE", "hiring backend developer", "hiring java developer",
        "hiring freshers software", "hiring full stack developer", "hiring software developer immediate joiners",
        "hiring 2025 batch software engineer", "hiring 2026 batch software engineer", "hiring junior software engineer",
        "hiring software engineer visa sponsorship", "hiring remote backend engineer"]},
}

# ----------------------------------------------------------------------------- shared helpers

_TAG_RX = re.compile(r"<[^>]+>")
_URL_RX = re.compile(r"https?://[^\s<>\"'\]\)]+")


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", s or "", flags=re.I)
    s = _TAG_RX.sub("", s)
    s = html_mod.unescape(s)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", s)).strip()


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_dt(s) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _get(url: str, params: dict | None = None, timeout: int = 25, accept: str = "*/*"):
    import requests
    return requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en"})


def make_record(platform: str, pid: str, url: str, text: str, posted_at: datetime | None, *, author: str = "",
                author_url: str = "", headline: str = "", reactions: int | None = None, comments: int | None = None,
                links: list[str] | None = None, query: str = "", now: datetime | None = None) -> dict | None:
    """One post, in the LinkedIn watcher's record shape (so the phone shows it the same way), plus `platform`."""
    now = now or datetime.now(timezone.utc)
    text = (text or "").strip()[:3000]
    if not text:
        return None
    pid = f"{platform}:{pid}"
    info = lp.classify(text, headline)
    text_links = [u.rstrip(".,;:!?)") for u in _URL_RX.findall(text)]
    rec = {
        "id": pid, "fp": lp.fingerprint(author, text), "platform": platform, "url": url, "link_kind": "post",
        "author": (author or platform)[:120], "author_url": author_url, "author_posts_url": author_url, "open_to_work": False,
        "headline": (headline or "")[:200], "posted_at": _iso(posted_at), "age_label": "", "text": text, "query": query, "queries": [query] if query else [],
        "reactions": reactions, "comments": comments, "links": lp.good_links(list(links or []) + text_links, author_url),
        "first_seen": _iso(now), "last_seen": _iso(now),
    }
    rec.update(info)
    return rec


# ----------------------------------------------------------------------------- telegram

def read_telegram(channel: str, now: datetime | None = None) -> list[dict]:
    """The public preview page of one channel: the last ~20 messages."""
    from bs4 import BeautifulSoup
    r = _get(f"https://t.me/s/{channel}", accept="text/html")
    if r.status_code != 200 or "tgme_widget_message" not in r.text:
        raise RuntimeError(f"t.me/s/{channel}: HTTP {r.status_code}, no messages (private channel or wrong name?)")
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for msg in soup.select("div.tgme_widget_message"):
        post = msg.get("data-post") or ""
        if "/" not in post:
            continue
        body = msg.select_one(".tgme_widget_message_text")
        text = strip_html(str(body)) if body else ""
        when = msg.select_one("time[datetime]")
        at = _parse_dt(when.get("datetime")) if when else None
        views = msg.select_one(".tgme_widget_message_views")
        v = views.get_text(strip=True) if views else ""
        n = None
        m = re.match(r"([\d.]+)\s*([KkMm]?)", v or "")
        if m:
            n = int(float(m.group(1)) * {"": 1, "k": 1000, "m": 1000000}[m.group(2).lower()])
        links = [a.get("href") for a in (body.select("a[href]") if body else []) if a.get("href", "").startswith("http")]
        author = msg.select_one(".tgme_widget_message_owner_name")
        rec = make_record("telegram", post.replace("/", "-"), f"https://t.me/{post}", text, at,
                          author=(author.get_text(strip=True) if author else channel), author_url=f"https://t.me/{channel}",
                          headline=f"Telegram channel @{channel}", reactions=n, links=links, query=f"@{channel}", now=now)
        if rec:
            out.append(rec)
    return out


# ----------------------------------------------------------------------------- reddit

_ATOM = "{http://www.w3.org/2005/Atom}"


def read_reddit(sub: str, now: datetime | None = None) -> list[dict]:
    """A subreddit's newest posts through its public RSS."""
    # reddit answers 429 to feeds asked back to back; one pause and one retry gets the next one through
    for attempt in (1, 2):
        r = _get(f"https://www.reddit.com/r/{sub}/new.rss", params={"limit": 50}, accept="application/atom+xml, application/xml, text/xml")
        if r.status_code == 429 and attempt == 1:
            time.sleep(random.uniform(20, 30))
            continue
        break
    if r.status_code != 200 or not r.text.lstrip().startswith("<?xml"):
        raise RuntimeError(f"r/{sub}: HTTP {r.status_code}")
    root = ET.fromstring(r.text)
    out = []
    for e in root.findall(f"{_ATOM}entry"):
        title = (e.findtext(f"{_ATOM}title") or "").strip()
        link = e.find(f"{_ATOM}link")
        url = link.get("href") if link is not None else ""
        at = _parse_dt(e.findtext(f"{_ATOM}published") or e.findtext(f"{_ATOM}updated"))
        author_el = e.find(f"{_ATOM}author")
        author = (author_el.findtext(f"{_ATOM}name") or "").strip() if author_el is not None else ""
        author_url = (author_el.findtext(f"{_ATOM}uri") or "").strip() if author_el is not None else ""
        content = strip_html(e.findtext(f"{_ATOM}content") or "")
        content = re.sub(r"\s*submitted by\s+/u/\S+.*$", "", content, flags=re.S)
        pid = (e.findtext(f"{_ATOM}id") or url).split("/")[-1] or url
        rec = make_record("reddit", re.sub(r"\W+", "", pid)[:40], url, f"{title}\n\n{content}".strip(), at, author=author,
                          author_url=author_url, headline=f"r/{sub}", query=f"r/{sub}", now=now)
        if rec:
            out.append(rec)
    return out


# ----------------------------------------------------------------------------- hacker news

def hn_current_thread() -> tuple[str, str] | None:
    r = _get("https://hn.algolia.com/api/v1/search_by_date",
             params={"query": "\"who is hiring\"", "tags": "story,author_whoishiring", "hitsPerPage": 3}, accept="application/json")
    r.raise_for_status()
    for h in r.json().get("hits") or []:
        if re.search(r"who is hiring", h.get("title") or "", re.I):
            return str(h["objectID"]), h.get("title") or ""
    return None


def read_hn(hours: float, now: datetime | None = None) -> list[dict]:
    """New comments on this month's 'Ask HN: Who is hiring?' thread, each one a job."""
    now = now or datetime.now(timezone.utc)
    found = hn_current_thread()
    if not found:
        raise RuntimeError("no 'Who is hiring' thread found")
    sid, title = found
    since = int((now - timedelta(hours=max(hours, 24) * 2)).timestamp())
    out = []
    for page in range(4):
        r = _get("https://hn.algolia.com/api/v1/search_by_date",
                 params={"tags": f"comment,story_{sid}", "numericFilters": f"created_at_i>{since}", "hitsPerPage": 100, "page": page},
                 accept="application/json")
        r.raise_for_status()
        data = r.json()
        for h in data.get("hits") or []:
            if h.get("parent_id") and str(h.get("parent_id")) != sid:
                continue        # replies, not job posts
            text = strip_html(h.get("comment_text") or "")
            at = _parse_dt(h.get("created_at"))
            rec = make_record("hn", str(h["objectID"]), f"https://news.ycombinator.com/item?id={h['objectID']}", text, at,
                              author=h.get("author") or "", author_url=f"https://news.ycombinator.com/user?id={h.get('author')}",
                              headline=title, query="HN who is hiring", now=now)
            if rec:
                out.append(rec)
        if page + 1 >= int(data.get("nbPages") or 1):
            break
    return out


# ----------------------------------------------------------------------------- mastodon / bluesky

def read_mastodon(instance: str, tag: str, now: datetime | None = None) -> list[dict]:
    r = _get(f"https://{instance}/api/v1/timelines/tag/{tag}", params={"limit": 40}, accept="application/json")
    if r.status_code != 200:
        raise RuntimeError(f"{instance} #{tag}: HTTP {r.status_code}")
    out = []
    for s in r.json():
        acct = s.get("account") or {}
        text = strip_html(s.get("content") or "")
        rec = make_record("mastodon", str(s.get("id")), s.get("url") or s.get("uri") or "", text, _parse_dt(s.get("created_at")),
                          author=acct.get("display_name") or acct.get("acct") or "", author_url=acct.get("url") or "",
                          headline=f"#{tag} on {instance}", reactions=s.get("favourites_count"), comments=s.get("replies_count"),
                          query=f"#{tag}", now=now)
        if rec:
            out.append(rec)
    return out


def read_bluesky(query: str, now: datetime | None = None) -> list[dict]:
    r = _get("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts", params={"q": query, "sort": "latest", "limit": 50},
             accept="application/json")
    if r.status_code != 200:
        raise RuntimeError(f"bluesky '{query}': HTTP {r.status_code}")
    out = []
    for p in r.json().get("posts") or []:
        rec_ = p.get("record") or {}
        a = p.get("author") or {}
        uri = p.get("uri") or ""
        rkey = uri.rsplit("/", 1)[-1]
        url = f"https://bsky.app/profile/{a.get('handle')}/post/{rkey}" if a.get("handle") and rkey else ""
        rec = make_record("bluesky", rkey or uri, url, rec_.get("text") or "", _parse_dt(rec_.get("createdAt")),
                          author=a.get("displayName") or a.get("handle") or "", author_url=f"https://bsky.app/profile/{a.get('handle')}",
                          headline="Bluesky", reactions=p.get("likeCount"), comments=p.get("replyCount"), query=query, now=now)
        if rec:
            out.append(rec)
    return out


# ----------------------------------------------------------------------------- x (twitter)

X_SEARCH = "https://x.com/search"
_X_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  document.querySelectorAll('article[data-testid="tweet"]').forEach(a => {
    const t = a.querySelector('time[datetime]');
    const link = t ? t.closest('a') : null;
    const href = link ? link.getAttribute('href') : '';
    const m = (href || '').match(/\/([^\/]+)\/status\/(\d+)/);
    if (!m) return;
    const body = a.querySelector('[data-testid="tweetText"]');
    const user = a.querySelector('[data-testid="User-Name"]');
    const name = user ? norm(user.innerText).split('\n')[0].split('@')[0] : '';
    const links = Array.from((body || a).querySelectorAll('a[href]')).map(x => x.getAttribute('href') || '').filter(h => /^https?:/.test(h));
    const count = sel => { const el = a.querySelector(sel); const v = el ? (el.getAttribute('aria-label') || el.innerText) : ''; const n = (v || '').match(/(\d[\d,]*)/); return n ? parseInt(n[1].replace(/,/g, ''), 10) : null; };
    out.push({id: m[2], handle: m[1], url: 'https://x.com' + href, at: t.getAttribute('datetime'),
              name: name, text: body ? body.innerText : norm(a.innerText).slice(0, 1500), links: links,
              likes: count('[data-testid="like"]'), replies: count('[data-testid="reply"]')});
  });
  return out;
}
"""


def login_x(state_path: Path = X_STATE_PATH, timeout_sec: int = 420, port: int = 9334) -> bool:
    """Open a browser, wait for a manual sign-in to X, save the session.

    X (and Apple / Google sign-in inside it) refuse an automation-controlled browser with
    "An unexpected error occurred", so the sign-in happens in a plain Chrome window with
    nothing attached - the same way the Naukri login works. Playwright connects only after
    X shows the home timeline, just long enough to copy the cookies. The bundled browser is
    the fallback when Chrome is not installed (email + password only there)."""
    from playwright.sync_api import sync_playwright
    from ..session import _chrome_path, launch_browser
    state_path.parent.mkdir(parents=True, exist_ok=True)
    chrome = _chrome_path()
    if chrome:
        import subprocess
        import urllib.request

        def open_tabs():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as resp:
                return json.loads(resp.read())

        profile_dir = state_path.parent / "chrome-login-profile"
        proc = subprocess.Popen([chrome, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
                                 "--no-first-run", "--no-default-browser-check", "--new-window", "https://x.com/login"])
        print("\n  A Chrome window is open. Sign in to X there (email/password, Apple or Google all work).")
        print(f"  Waiting up to {timeout_sec // 60} minutes...\n")
        deadline = time.time() + timeout_sec
        try:
            while time.time() < deadline:
                try:
                    tabs = open_tabs()
                except Exception:  # noqa: BLE001 - Chrome still starting, or closed
                    if proc.poll() is not None:
                        print("  The browser was closed before the login finished.")
                        return False
                    time.sleep(1)
                    continue
                if any(t.get("type") == "page" and re.search(r"https://(x|twitter)\.com/(home|explore|notifications)", t.get("url", "")) for t in tabs):
                    time.sleep(3)
                    with sync_playwright() as p:
                        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                        browser.contexts[0].storage_state(path=str(state_path))
                    print(f"  Login captured. Session saved to {state_path}")
                    return True
                time.sleep(1)
            print("  Timed out waiting for login.")
            return False
        finally:
            if proc.poll() is None:
                proc.terminate()
    with sync_playwright() as p:
        browser = launch_browser(p, headless=False, interactive=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto("https://x.com/login", wait_until="domcontentloaded")
        print("\n  A browser window is open. Sign in to X there (finish any code / captcha).")
        print(f"  Waiting up to {timeout_sec // 60} minutes...\n")
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if "/home" in page.url or page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').count():
                page.wait_for_timeout(3000)
                context.storage_state(path=str(state_path))
                print(f"  Login captured. Session saved to {state_path}")
                browser.close()
                return True
            page.wait_for_timeout(1000)
        print("  Timed out waiting for login.")
        browser.close()
        return False


def read_x(queries: list[str], headless: bool = True, now: datetime | None = None, state_path: Path = X_STATE_PATH) -> tuple[list[dict], list[str]]:
    """X's search, Latest tab, for each query. Returns (records, errors)."""
    from playwright.sync_api import sync_playwright
    from ..session import launch_browser, new_context
    if not state_path.exists():
        raise RuntimeError(f"No saved X session at {state_path}. Run: python -m naukri.jobs.social_posts --login-x")
    out, errors = [], []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=headless)
        ctx = new_context(browser, storage_state=str(state_path), viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        try:
            for i, q in enumerate(queries):
                try:
                    page.goto(f"{X_SEARCH}?q={q}&src=typed_query&f=live", wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(random.uniform(5000, 8000))
                    if "/login" in page.url or "/i/flow/login" in page.url:
                        raise RuntimeError(f"X session expired: run python -m naukri.jobs.social_posts --login-x")
                    for _ in range(3):
                        page.mouse.wheel(0, 1500)
                        page.wait_for_timeout(random.uniform(1200, 2000))
                    cards = page.evaluate(_X_JS) or []
                except Exception as exc:  # noqa: BLE001
                    if "session expired" in str(exc):
                        raise
                    errors.append(f"x '{q}': {str(exc)[:120]}")
                    cards = []
                for c in cards:
                    rec = make_record("x", c["id"], c["url"], c.get("text") or "", _parse_dt(c.get("at")), author=c.get("name") or c.get("handle") or "",
                                      author_url=f"https://x.com/{c.get('handle')}", headline=f"@{c.get('handle')} on X",
                                      reactions=c.get("likes"), comments=c.get("replies"), links=c.get("links"), query=q, now=now)
                    if rec:
                        out.append(rec)
                log.info("  x %-44s %2d post(s)", q, len(cards))
                if i < len(queries) - 1:
                    time.sleep(random.uniform(4, 9))
        finally:
            browser.close()
    return out, errors


# ----------------------------------------------------------------------------- config, store, publish

def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for k, v in (data.items() if isinstance(data, dict) else []):
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                # YAML 1.1 reads the bare key `on` as the boolean True; it means the "on" switch here
                cfg[k].update({("on" if kk is True else kk): vv for kk, vv in v.items() if vv is not None})
            elif v is not None:
                cfg[k] = v
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("social.yaml not read (%s); defaults used", exc)
    return cfg


def load_store(path: Path = STORE_PATH) -> dict:
    store = lp.load_store(path)
    store.setdefault("cursors", {})
    return store


def publish(payload: dict) -> bool:
    tools = ROOT.parent / "site" / "tools"
    if not (tools / "pages_git.py").exists():
        log.warning("publish skipped: %s not found", tools)
        return False
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import pages_git  # type: ignore
        repo_url = None
        try:
            from phone_publish import load_config as _phone_cfg  # type: ignore
            repo_url = (_phone_cfg() or {}).get("repo_url")
        except (SystemExit, Exception):  # noqa: BLE001
            repo_url = None
        repo_url = repo_url or pages_git.default_repo_url()
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        pages_git.put_file(repo_url, PUBLISH_PATH, text,
                           "social posts: %d hiring post(s) in the last %gh" % (payload.get("count", 0), payload.get("window_hours", WINDOW_HOURS)))
        return True
    except (SystemExit, Exception) as exc:  # noqa: BLE001
        log.warning("publish failed: %s", str(exc)[:300])
        return False


def payload_for(store: dict, hours: float = WINDOW_HOURS, now: datetime | None = None, limit: int = MAX_PUBLISHED) -> dict:
    payload = lp.payload_for(store, hours, now, limit)
    payload["every_minutes"] = store.get("every_minutes") or EVERY_MINUTES
    payload["sources"] = store.get("sources") or {}
    payload["platforms"] = sorted({p.get("platform", "") for p in payload["posts"]})
    return payload


# ----------------------------------------------------------------------------- a pass

def _rotate(store: dict, key: str, items: list, n: int) -> list:
    if not items:
        return []
    cur = int(store["cursors"].get(key) or 0) % len(items)
    batch = [items[(cur + i) % len(items)] for i in range(min(n, len(items)))]
    store["cursors"][key] = (cur + len(batch)) % len(items)
    return batch


def run_once(cfg: dict, hours: float = WINDOW_HOURS, headless: bool = True, sources: list[str] | None = None,
             do_publish: bool = True, store_path: Path = STORE_PATH) -> dict:
    store = load_store(store_path)
    now = datetime.now(timezone.utc)
    t0 = time.time()
    read: list[dict] = []
    errors: list[str] = []
    per_source: dict[str, int] = {}
    on = lambda name: (sources is None or name in sources) and bool((cfg.get(name) or {}).get("on", True))  # noqa: E731

    def take(name: str, fn, label: str):
        try:
            recs = fn()
            read.extend(recs)
            per_source[name] = per_source.get(name, 0) + len(recs)
            log.info("  %-9s %-40s %3d post(s)", name, label, len(recs))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name} {label}: {str(exc)[:120]}")
            log.warning("  %-9s %-40s failed: %s", name, label, str(exc)[:160])
        time.sleep(random.uniform(1.0, 2.5))

    if on("telegram"):
        for ch in cfg["telegram"].get("channels") or []:
            take("telegram", lambda ch=ch: read_telegram(ch, now), f"@{ch}")
    if on("reddit"):
        for sub in cfg["reddit"].get("subreddits") or []:
            take("reddit", lambda sub=sub: read_reddit(sub, now), f"r/{sub}")
            time.sleep(random.uniform(6, 10))
    if on("hn"):
        take("hn", lambda: read_hn(hours, now), "who is hiring")
    if on("mastodon"):
        inst = cfg["mastodon"].get("instance") or "mastodon.social"
        for tag in cfg["mastodon"].get("tags") or []:
            take("mastodon", lambda tag=tag: read_mastodon(inst, tag, now), f"#{tag}")
    if on("bluesky"):
        for q in cfg["bluesky"].get("queries") or []:
            take("bluesky", lambda q=q: read_bluesky(q, now), q)
    if on("x"):
        qs = _rotate(store, "x", list(cfg["x"].get("queries") or []), int(cfg["x"].get("per_pass") or 4))
        if not X_STATE_PATH.exists():
            log.info("  x: no saved session (python -m naukri.jobs.social_posts --login-x); skipped")
        elif qs:
            try:
                recs, errs = read_x(qs, headless=headless, now=now)
                read.extend(recs)
                errors.extend(errs)
                per_source["x"] = len(recs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"x: {str(exc)[:160]}")
                log.warning("  x failed: %s", str(exc)[:200])

    new = lp.merge(store, read, now, KEEP_HOURS)
    store["updated"] = _iso(now)
    store["window_hours"] = hours
    store["every_minutes"] = cfg.get("every_minutes") or EVERY_MINUTES
    store["sources"] = per_source
    store["queries"] = [f"telegram: {len(cfg['telegram'].get('channels') or [])} channels", f"reddit: {len(cfg['reddit'].get('subreddits') or [])} subreddits",
                        "HN who is hiring", f"mastodon: {len(cfg['mastodon'].get('tags') or [])} tags", f"x: {len(cfg['x'].get('queries') or [])} searches"]
    pc = store.setdefault("pc", {})
    pc.update({"host": os.environ.get("COMPUTERNAME", ""), "last_pass": store["updated"], "passes": int(pc.get("passes") or 0) + 1,
               "last_read": len(read), "last_new": new, "last_errors": errors[:8], "last_error": "", "seconds": round(time.time() - t0, 1)})
    lp.save_store(store, store_path)
    payload = payload_for(store, hours, now)
    wanted_n = sum(1 for r in read if lp.wanted(r))
    log.info("pass done: %d post(s) read (%s), %d new, %d hiring for 0-2 yrs this pass, %d published for the last %gh (%.0fs)%s",
             len(read), ", ".join(f"{k} {v}" for k, v in per_source.items()), new, wanted_n, payload["count"], hours, time.time() - t0,
             f"; {len(errors)} source error(s)" if errors else "")
    if do_publish:
        publish(payload)
    return payload


def loop(cfg: dict, every_minutes: int = EVERY_MINUTES, hours: float = WINDOW_HOURS, headless: bool = True) -> int:
    log.info("social hiring-posts watcher: every %d min, posts from the last %gh", every_minutes, hours)
    while True:
        started = time.time()
        try:
            run_once(cfg, hours=hours, headless=headless)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001
            log.exception("pass failed: %s", exc)
        sleep_for = max(60, every_minutes * 60 - (time.time() - started) + random.uniform(-120, 120))
        log.info("next pass in %.0f min", sleep_for / 60)
        time.sleep(sleep_for)


def _setup_logging(verbose: bool) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", handlers=handlers)
    for noisy in ("urllib3", "naukri.jobs.linkedin_posts"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    mode.add_argument("--login-x", action="store_true", dest="login_x", help="sign in to X once; the session is saved")
    mode.add_argument("--publish-only", action="store_true", dest="publish_only")
    ap.add_argument("--every", type=int, default=EVERY_MINUTES, metavar="MIN")
    ap.add_argument("--hours", type=float, default=WINDOW_HOURS, metavar="N")
    ap.add_argument("--source", help="comma-separated: telegram,reddit,hn,mastodon,bluesky,x (default: every source that is on)")
    ap.add_argument("--show", action="store_true", help="X read in a visible browser")
    ap.add_argument("--no-publish", action="store_true", dest="no_publish")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    _setup_logging(args.verbose)
    if args.login_x:
        return 0 if login_x() else 1
    cfg = load_config()
    if args.show:
        os.environ["NAUKRI_SHOW"] = "1"
        os.environ.pop("NAUKRI_BACKGROUND", None)
    else:
        os.environ["NAUKRI_BACKGROUND"] = "1"
    lp._guard_children()
    lp._keep_awake()
    if args.publish_only:
        return 0 if publish(payload_for(load_store(), args.hours)) else 1
    sources = [s.strip() for s in args.source.split(",") if s.strip()] if args.source else None
    if args.loop:
        return loop(cfg, args.every, args.hours, headless=not args.show)
    payload = run_once(cfg, hours=args.hours, headless=not args.show, sources=sources, do_publish=not args.no_publish)
    print(f"\n  {payload['count']} hiring post(s) for 0-2 yrs in the last {args.hours:g} h from {', '.join(payload['platforms']) or 'nowhere'} "
          f"({payload['seen_total']} posts remembered). Store: {STORE_PATH}\n")
    for p in payload["posts"][:15]:
        print(f"  {p['hours_old']:>5.1f}h  {p.get('platform', ''):<9} {', '.join(p.get('roles') or [])[:30]:<30} "
              f"{(p.get('exp') or {}).get('text') or ('fresher' if (p.get('exp') or {}).get('entry') else '-'):<12} {p['author'][:24]:<24} {p['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
