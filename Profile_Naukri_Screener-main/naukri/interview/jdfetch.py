"""Fetch the full job description for the Top 10.

The scan does not have this. Naukri's search endpoint returns `jobDescription`
as a teaser - on today's Top 10 that ranged from 31 to 811 characters, and a
31-character JD analysed for "required skills" produces nothing worth studying.
The full text only exists on the job's own page, behind a second API call the
page makes for itself:

    /jobapi/v4/job/<jobId>     the whole posting, as JSON

Same signing constraint as the search endpoint, so this is one real navigation
per job. Ten navigations, spaced like a person reading ten postings.

Two fallbacks, in order, because a JD page that renders but whose API shape has
moved should still yield text:

    1. the v4 payload's jobDescription / keyRoles / education fields
    2. the rendered description container in the DOM
    3. whatever the scan already had (the teaser)

`jd_source` on each result records which one produced the text, so a thin
analysis can always be traced back to a thin fetch rather than a bad model.
"""
from __future__ import annotations

import logging
import random
import re
import time

log = logging.getLogger("naukri.interview.jdfetch")

JOB_API = "jobapi/v4/job"
API_WAIT_SEC = 20

# The rendered JD container. Naukri hashes its class names per build, so match
# on the stable prefix rather than the whole token.
DOM_SELECTORS = (
    "[class*='dang-inner-html']",
    "section.job-desc",
    "div.job-desc",
    "[class*='JDC__dang']",
    "[itemprop='description']",
)


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _from_payload(payload: dict) -> tuple[str, dict]:
    """Pull the description and the structured extras out of a v4 job payload."""
    detail = payload.get("jobDetails") or payload.get("jobdetails") or payload
    if not isinstance(detail, dict):
        return "", {}

    parts = [_strip_html(detail.get("description") or detail.get("jobDescription"))]

    roles = detail.get("keyRoles") or detail.get("keySkills")
    if isinstance(roles, str) and roles.strip():
        parts.append("Key skills: " + _strip_html(roles))

    education = detail.get("education")
    if isinstance(education, dict):
        bits = [f"{k}: {v}" for k, v in education.items() if v]
        if bits:
            parts.append("Education - " + "; ".join(bits))
    elif isinstance(education, str) and education.strip():
        parts.append("Education: " + _strip_html(education))

    extras = {
        "industry": detail.get("industry"),
        "functional_area": detail.get("functionalArea") or detail.get("functionalAreaName"),
        "role_category": detail.get("roleCategory"),
        "role": detail.get("role"),
        "employment_type": detail.get("employmentType"),
    }
    extras = {k: v for k, v in extras.items() if v}

    tags = detail.get("keySkills") or {}
    if isinstance(tags, dict):
        preferred = [t.get("label") or t.get("value") for t in (tags.get("preferred") or [])]
        other = [t.get("label") or t.get("value") for t in (tags.get("other") or [])]
        skills = [s for s in preferred + other if s]
        if skills:
            extras["skills"] = skills
            parts.append("Skills listed: " + ", ".join(skills))

    return "\n\n".join(p for p in parts if p), extras


def _from_dom(page) -> str:
    for selector in DOM_SELECTORS:
        try:
            node = page.locator(selector).first
            if node.count() == 0:
                continue
            text = node.inner_text(timeout=4000)
            if text and len(text.strip()) > 120:
                return re.sub(r"\n\s*\n\s*\n+", "\n\n", text.strip())
        except Exception:
            continue
    return ""


def fetch_one(page, job: dict) -> dict:
    """Fetch the full JD for one job dict. Never raises - returns what it got."""
    url = job.get("url") or ""
    fallback = (job.get("description") or "").strip()
    result = {"jd_text": fallback, "jd_source": "search-teaser" if fallback else "none",
              "jd_extras": {}}
    if not url:
        return result

    payloads: list[dict] = []

    def handler(response):
        if JOB_API not in response.url:
            return
        try:
            if "json" not in (response.headers.get("content-type") or ""):
                return
            payloads.append(response.json())
        except Exception:
            return

    page.on("response", handler)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        deadline = time.time() + API_WAIT_SEC
        while time.time() < deadline and not payloads:
            page.wait_for_timeout(400)
        page.wait_for_timeout(1200)
    except Exception as exc:
        log.warning("  %s: navigation failed (%s)", job.get("title", "?")[:38], str(exc)[:120])
    finally:
        page.remove_listener("response", handler)

    for payload in payloads:
        text, extras = _from_payload(payload)
        if len(text) > len(result["jd_text"]):
            result.update(jd_text=text, jd_source="jobapi/v4", jd_extras=extras)
        elif extras and not result["jd_extras"]:
            result["jd_extras"] = extras

    if len(result["jd_text"]) < 400:
        dom_text = _from_dom(page)
        if len(dom_text) > len(result["jd_text"]):
            result.update(jd_text=dom_text, jd_source="dom")

    return result


def _pause() -> None:
    time.sleep(random.uniform(2.0, 4.5))


def fetch(jobs: list[dict], headless: bool = False) -> list[dict]:
    """Return `jobs` with jd_text / jd_source / jd_extras filled in.

    Headed by default for the same Akamai reason as every other Naukri run -
    headless Chromium gets an "Access Denied" body, which would leave every JD
    on the teaser fallback and quietly halve the quality of the analysis.
    """
    from playwright.sync_api import sync_playwright

    from ..session import DEFAULT_STATE, open_profile

    enriched = [dict(job) for job in jobs]
    log.info("Fetching full JDs for %d job(s)", len(enriched))

    with sync_playwright() as p:
        browser, _ctx, page = open_profile(p, DEFAULT_STATE, headless=headless)
        try:
            for index, job in enumerate(enriched, start=1):
                before = len((job.get("description") or "").strip())
                job.update(fetch_one(page, job))
                log.info("  %2d. %-42s %5d chars (%s, was %d)",
                         index, (job.get("title") or "")[:42],
                         len(job["jd_text"]), job["jd_source"], before)
                if index < len(enriched):
                    _pause()
        finally:
            browser.close()

    thin = [j for j in enriched if len(j.get("jd_text") or "") < 250]
    if thin:
        log.warning("%d JD(s) came back under 250 chars - the posting itself is "
                    "short, or the session needs refreshing", len(thin))
    return enriched
