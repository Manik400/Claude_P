"""Check that each job-source API key is set and accepted, without printing it.

    python job-hunt/scripts/check_keys.py

Reads the same .env files as job_bot.py. Each check is the cheapest call the
API offers (account info where there is one); JSearch has none, so it spends
one request of the free monthly quota.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jobbot.dotenv import load_env  # noqa: E402


def call(url, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        return e.code, body
    except (urllib.error.URLError, TimeoutError) as e:
        return None, {"error": str(e)}


def apify(env):
    code, body = call("https://api.apify.com/v2/users/me?" + urllib.parse.urlencode({"token": env["APIFY_TOKEN"]}))
    if code == 200:
        d = body.get("data") or {}
        return True, "user %s, plan %s" % (d.get("username"), (d.get("plan") or {}).get("id"))
    return False, "HTTP %s - token wrong or revoked" % code


def firecrawl(env):
    code, body = call("https://api.firecrawl.dev/v1/team/credit-usage",
                      {"Authorization": "Bearer " + env["FIRECRAWL_API_KEY"]})
    if code == 200:
        return True, "%s credits left" % (body.get("data") or {}).get("remaining_credits")
    return False, "HTTP %s - key wrong, or out of credits" % code


def jsearch(env):
    q = urllib.parse.urlencode({"query": "python developer in India", "num_pages": 1, "country": "in"})
    code, body = call("https://jsearch.p.rapidapi.com/search?" + q,
                      {"X-RapidAPI-Key": env["RAPIDAPI_KEY"], "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
    if code == 200:
        return True, "%d jobs returned" % len(body.get("data") or [])
    hint = {403: "not subscribed to JSearch - press Subscribe (Basic, free) on its RapidAPI page",
            401: "key wrong", 429: "monthly free quota used up"}.get(code, body.get("message", ""))
    return False, "HTTP %s - %s" % (code, hint)


def adzuna(env):
    q = urllib.parse.urlencode({"app_id": env["ADZUNA_APP_ID"], "app_key": env["ADZUNA_APP_KEY"],
                                "results_per_page": 1, "what": "python"})
    code, body = call("https://api.adzuna.com/v1/api/jobs/in/search/1?" + q)
    return (True, "%s jobs" % body.get("count")) if code == 200 else (False, "HTTP %s - id/key wrong" % code)


def jooble(env):
    code, body = call("https://jooble.org/api/" + env["JOOBLE_API_KEY"], {"Content-Type": "application/json"},
                      json.dumps({"keywords": "python", "location": "India"}).encode())
    return (True, "%s jobs" % body.get("totalCount")) if code == 200 else (False, "HTTP %s - key wrong" % code)


CHECKS = [
    ("Apify", ("APIFY_TOKEN",), apify),
    ("Firecrawl", ("FIRECRAWL_API_KEY",), firecrawl),
    ("JSearch (Google Jobs)", ("RAPIDAPI_KEY",), jsearch),
    ("Adzuna", ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"), adzuna),
    ("Jooble", ("JOOBLE_API_KEY",), jooble),
]


def main():
    load_env()
    bad = 0
    for name, keys, fn in CHECKS:
        missing = [k for k in keys if not os.environ.get(k, "").strip()]
        if missing:
            print("%-22s NOT SET   (%s)" % (name, ", ".join(missing)))
            bad += 1
            continue
        ok, note = fn({k: os.environ[k].strip() for k in keys})
        print("%-22s %-9s %s" % (name, "OK" if ok else "FAILED", note))
        bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
