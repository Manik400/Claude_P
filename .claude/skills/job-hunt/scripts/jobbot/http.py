"""Polite HTTP client: shared session, per-host rate limiting, retries, logging."""
import threading
import time
from urllib.parse import urlparse

import requests

from .config import USER_AGENT

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

BLOCK_MARKERS = ("just a moment", "access denied", "security check", "verify you are human",
                 "captcha", "attention required", "cf-chl", "recaptcha required")


class Blocked(Exception):
    """Raised when a site answers with a bot-protection page."""


class Http:
    def __init__(self, log=None, min_interval=0.8, timeout=25):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.log = log or (lambda *a, **k: None)
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = {}
        self._lock = threading.Lock()
        self.requests_made = 0

    def _throttle(self, url):
        host = urlparse(url).netloc
        with self._lock:
            last = self._last.get(host, 0)
            wait = self.min_interval - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.time()

    def get(self, url, params=None, headers=None, retries=2, allow_block=False, **kw):
        return self.request("GET", url, params=params, headers=headers, retries=retries, allow_block=allow_block, **kw)

    def post(self, url, json=None, data=None, headers=None, retries=1, **kw):
        return self.request("POST", url, json=json, data=data, headers=headers, retries=retries, **kw)

    def request(self, method, url, retries=2, allow_block=False, **kw):
        kw.setdefault("timeout", self.timeout)
        last_exc = None
        for attempt in range(retries + 1):
            self._throttle(url)
            try:
                r = self.session.request(method, url, **kw)
                self.requests_made += 1
                if r.status_code in (403, 429, 503) or (r.status_code == 406 and "recaptcha" in r.text[:200].lower()):
                    body = r.text[:4000].lower()
                    if r.status_code == 403 or any(m in body for m in BLOCK_MARKERS):
                        if allow_block:
                            return r
                        raise Blocked(f"{r.status_code} from {urlparse(url).netloc}")
                    if r.status_code == 429 and attempt < retries:
                        time.sleep(2.0 * (attempt + 1))
                        continue
                if r.status_code >= 500 and attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return r
            except Blocked:
                raise
            except requests.RequestException as e:
                last_exc = e
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
        raise last_exc if last_exc else RuntimeError("request failed")

    def get_json(self, url, params=None, headers=None, **kw):
        r = self.get(url, params=params, headers=headers, **kw)
        r.raise_for_status()
        return r.json()

    def get_html(self, url, params=None, headers=None, **kw):
        r = self.get(url, params=params, headers=headers, **kw)
        r.raise_for_status()
        return r.text
