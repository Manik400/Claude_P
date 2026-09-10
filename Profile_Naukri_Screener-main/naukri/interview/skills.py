"""Extract skills from the Top 10 JDs and match them against your profile.

This is deliberately *not* a model's job. Counting how many of ten documents
contain a term is arithmetic, and a language model asked to do it will produce
a plausible number rather than a correct one - which matters here because the
count is the whole basis of "study this first". So the matrix is built by
matching a curated lexicon, and the model is handed the finished counts to
reason about rather than asked to produce them.

The lexicon is field-shaped on purpose. A generic skill extractor pulls
"communication" and "stakeholder management" out of every JD and buries the
three tools that actually decide the interview. So the lexicon comes from the
role pack named in jobs.yaml - `roles/qa-automation.yaml`, `roles/support.yaml`
and so on - and each pack lists the vocabulary of one field. See docs/ROLES.md.

Matching rules that earn their keep:

  * aliases fold spellings together - "CI/CD", "CICD" and "continuous
    integration" are one row, not three
  * word boundaries everywhere, so "Java" does not match "JavaScript" and
    "API" does not match "rapid"
  * where a term is found in your resume decides how strong the claim is:
    a bullet in the experience section is Strong, a comma in a skills list
    is Moderate. See profile.load() for why they are kept apart.
"""
from __future__ import annotations

import re
from collections import OrderedDict

from naukri import roles

# canonical name -> (category, aliases), loaded from the active role pack. The
# canonical name is what the page and the prompts show, so a pack writes it the
# way people say it.
#
# Loaded at import rather than per call: the aliases are compiled into regexes
# below, and a 100-question run walks the lexicon thousands of times. Switching
# role means editing jobs.yaml and running again, which is a new process.
_PACK = roles.load()

LEXICON: "OrderedDict[str, tuple[str, tuple[str, ...]]]" = _PACK["lexicon"]

# Terms whose bare form is too common to trust a substring match on.
_TIGHT = _PACK["tight_terms"]

#: The role this matrix is built for, shown on the study page and in prompts.
ROLE_LABEL = _PACK["label"]
PRIMARY_ROLE = _PACK["primary_role"]


def _pattern(alias: str) -> re.Pattern:
    escaped = re.escape(alias)
    # Word boundaries do not fire next to punctuation like "c#" or "ci/cd", so
    # fall back to a lookaround on non-word characters for those.
    if re.match(r"^\w", alias) and re.search(r"\w$", alias):
        return re.compile(rf"\b{escaped}\b", re.I)
    return re.compile(rf"(?<![\w]){escaped}(?![\w])", re.I)


_COMPILED = {
    canonical: [(_pattern(alias), alias) for alias in aliases]
    for canonical, (_category, aliases) in LEXICON.items()
}


def find(text: str) -> dict[str, str]:
    """Canonical skill -> the alias that matched, for one document."""
    if not text:
        return {}
    hits = {}
    for canonical, patterns in _COMPILED.items():
        for pattern, alias in patterns:
            if pattern.search(text):
                hits[canonical] = alias
                break
    return hits


def job_text(job: dict) -> str:
    """Everything about one job that a skill could be named in."""
    return "\n".join(str(part) for part in (
        job.get("title") or "",
        " ".join(job.get("skills") or []),
        " ".join((job.get("jd_extras") or {}).get("skills") or []),
        (job.get("jd_extras") or {}).get("role") or "",
        (job.get("jd_extras") or {}).get("industry") or "",
        (job.get("jd_extras") or {}).get("functional_area") or "",
        job.get("jd_text") or job.get("description") or "",
    ) if part)


def _profile_status(canonical: str, profile: dict) -> tuple[str, str]:
    """(status, evidence) for one skill against the profile.

    Strong needs the skill to appear in the resume's own narrative - the
    experience bullets and project write-ups - or to carry three or more
    stated years. Anything found only in a skills list is Moderate: it is a
    claim you have made, not one you have described.
    """
    patterns = _COMPILED[canonical]
    aliases = LEXICON[canonical][1]

    years = profile.get("skill_years") or {}
    stated = None
    for alias in aliases + (canonical.lower(),):
        if alias in years:
            stated = max(stated or 0, years[alias])

    def hit(text: str) -> str | None:
        if not text:
            return None
        for pattern, alias in patterns:
            match = pattern.search(text)
            if match:
                return alias
        return None

    in_narrative = hit(profile.get("narrative", ""))
    in_listed = hit(profile.get("listed_skills_text", ""))
    in_keys = hit(" ".join(profile.get("key_skills") or []))
    in_it = hit(" ".join(profile.get("it_skills") or []))
    in_resume = hit(profile.get("resume_text", ""))

    if in_narrative or (stated is not None and stated >= 3):
        bits = []
        if in_narrative:
            bits.append("described in resume experience")
        if stated is not None:
            bits.append(f"{stated:g} years stated")
        return "strong", "; ".join(bits)

    if in_listed or in_keys or in_it or in_resume or stated is not None:
        where = ("resume skills list" if in_listed else
                 "Naukri key skills" if in_keys else
                 "Naukri IT skills" if in_it else
                 "mentioned in resume" if in_resume else
                 f"{stated:g} years stated")
        extra = f"; {stated:g} years stated" if stated is not None and not in_listed else ""
        return "moderate", where + extra

    return "gap", "not found in resume or profile"


def importance(jd_count: int, total: int) -> str:
    if total <= 0:
        return "Low"
    share = jd_count / total
    if share >= 0.6:
        return "Critical"
    if share >= 0.35:
        return "High"
    if share >= 0.2:
        return "Medium"
    return "Low"


def matrix(jobs: list[dict], profile: dict) -> list[dict]:
    """The §6 skill matrix: one row per skill named in at least one JD.

    Sorted by how much of the market wants it, then by how exposed you are -
    a Critical skill you have a gap in belongs at the top of a study list, not
    filed alphabetically halfway down.
    """
    total = len(jobs)
    per_job = [find(job_text(job)) for job in jobs]

    rows = []
    for canonical, (category, _aliases) in LEXICON.items():
        mentions = [i for i, hits in enumerate(per_job) if canonical in hits]
        if not mentions:
            continue
        status, evidence = _profile_status(canonical, profile)
        rows.append({
            "skill": canonical,
            "category": category,
            "jd_count": len(mentions),
            "jd_total": total,
            "jds": [i + 1 for i in mentions],          # 1-based, matches the page
            "importance": importance(len(mentions), total),
            "profile_match": {"strong": "Strong", "moderate": "Moderate",
                              "gap": "Gap"}[status],
            "status": status,
            "evidence": evidence,
        })

    rank = {"gap": 0, "moderate": 1, "strong": 2}
    rows.sort(key=lambda r: (-r["jd_count"], rank[r["status"]], r["skill"]))
    return rows


def buckets(rows: list[dict]) -> dict[str, list[dict]]:
    """Split the matrix into the three §4 lists, each already prioritised."""
    return {
        "strong": [r for r in rows if r["status"] == "strong"],
        "moderate": [r for r in rows if r["status"] == "moderate"],
        "gap": [r for r in rows if r["status"] == "gap"],
    }


def study_order(rows: list[dict], limit: int = 30) -> list[dict]:
    """What to revise first: demand weighted by how exposed you are.

    A Critical skill you have never used outranks a Critical skill you use
    daily, because the interview risk is not in what you know.
    """
    weight = {"gap": 1.0, "moderate": 0.6, "strong": 0.25}
    scored = sorted(
        rows,
        key=lambda r: -(r["jd_count"] / max(r["jd_total"], 1)) * weight[r["status"]],
    )
    return scored[:limit]
