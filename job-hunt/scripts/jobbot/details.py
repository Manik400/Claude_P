"""Fetch full job descriptions for the most promising jobs (better match scores, experience parsing)."""
import json
import re

from .experience import annotate
from .textutil import html_to_text, normalize_ws, soup


def generic_details(ctx, job):
    """JSON-LD JobPosting -> og:description -> largest text block."""
    r = ctx.http.get(job.url, allow_block=True)
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        return None
    html = r.text
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and it.get("@type") in ("JobPosting",) and it.get("description"):
                text = html_to_text(it["description"])
                if it.get("employmentType") and not job.employment_type:
                    job.employment_type = str(it["employmentType"]).replace("_", " ").title()
                if isinstance(it.get("baseSalary"), dict) and not job.salary:
                    val = it["baseSalary"].get("value") or {}
                    if isinstance(val, dict) and (val.get("minValue") or val.get("value")):
                        job.salary = normalize_ws(f"{val.get('minValue') or val.get('value')} - {val.get('maxValue') or ''} {it['baseSalary'].get('currency') or ''}")
                return text
    s = soup(html)
    for t in s(["script", "style", "noscript", "nav", "header", "footer", "form"]):
        t.decompose()
    best = ""
    for sel in ("article", "main", "[class*=description]", "[id*=description]", "section", "div"):
        for el in s.select(sel):
            txt = el.get_text(" ", strip=True)
            if len(txt) > len(best):
                best = txt
        if len(best) > 1500:
            break
    best = normalize_ws(best)
    return best[:12000] if len(best) > 200 else None


def fetch_details(ctx, jobs, sources_by_key, limit=40, log=print):
    candidates = [j for j in jobs if len(j.description) < 250 and j.url.startswith("http")]
    candidates.sort(key=lambda j: (-j.relevance, -(1 if j.fit == "fit" else 0), j.posted or ""), reverse=False)
    todo = candidates[:limit]
    log(f"details: fetching descriptions for {len(todo)} of {len(candidates)} jobs without one")
    done = 0
    for j in todo:
        src = sources_by_key.get(j.source)
        try:
            text = None
            if src is not None and hasattr(src, "fetch_details"):
                text = src.fetch_details(ctx, j)
            if text is None:
                text = generic_details(ctx, j)
        except Exception as e:  # noqa: BLE001
            log(f"  details failed for {j.source}:{j.id}: {type(e).__name__}: {str(e)[:100]}")
            continue
        if text and len(text) > len(j.description):
            j.description = text
            if not j.snippet:
                j.snippet = text[:400]
            j.extra["details_fetched"] = True
            j.exp_min, j.exp_max = None, None  # re-parse with the full text
            annotate(j, ctx.user_years)
            done += 1
    log(f"details: {done} descriptions added")
    return done
