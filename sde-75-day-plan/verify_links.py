"""Check every LeetCode link in plan.json against LeetCode itself.

    python verify_links.py

For each problem it asks LeetCode's public GraphQL endpoint for the slug and
reports slugs that do not exist, difficulties that differ from the plan, and
Premium-only problems. Results are cached in content/leetcode_cache.json so a
re-run only asks about new slugs.
"""
import json
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "content" / "leetcode_cache.json"
Q = "query q($s:String!){question(titleSlug:$s){title difficulty isPaidOnly}}"


def lookup(slug):
    body = json.dumps({"query": Q, "variables": {"s": slug}}).encode()
    req = urllib.request.Request("https://leetcode.com/graphql", data=body, headers={
        "Content-Type": "application/json", "Referer": "https://leetcode.com", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return (json.loads(r.read()).get("data") or {}).get("question")


def main():
    plan = json.loads((HERE / "plan.json").read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    items = []
    for d in plan["days"]:
        for q in d["leetcode"]:
            items.append((d["day"], "LC", q["name"], q["url"], q["difficulty"]))
        for kind in ("sql", "design"):
            x = d[kind]
            if x.get("url"):
                items.append((d["day"], kind.upper(), x["name"], x["url"], x["difficulty"]))
    bad = 0
    for day, kind, name, url, diff in items:
        slug = url.rstrip("/").rsplit("/", 1)[1]
        if slug not in cache:
            for attempt in range(3):
                try:
                    cache[slug] = lookup(slug)
                    break
                except Exception as exc:  # rate limit / network: back off and retry
                    time.sleep(2 + 3 * attempt)
            else:
                print(f"?? day {day} {kind} {name}: could not reach LeetCode")
                continue
            time.sleep(0.25)
        info = cache[slug]
        if not info:
            print(f"MISSING  day {day} {kind} {name} ({slug})"); bad += 1
        elif info["difficulty"] != diff:
            print(f"DIFF     day {day} {kind} {name}: plan says {diff}, LeetCode says {info['difficulty']}"); bad += 1
        elif info["isPaidOnly"]:
            print(f"PREMIUM  day {day} {kind} {name}"); bad += 1
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    print(f"checked {len(items)} links, {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
