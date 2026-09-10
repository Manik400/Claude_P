"""Your side of the comparison: resume text, profile skills, years per skill.

Three sources, deliberately kept separate rather than merged into one blob,
because the *strength* of a claim depends on where it came from:

    resume/*.txt          the narrative - what you actually did, in sentences
    data/profile.json     the Naukri profile - key_skills, it_skills, employment
    jobs.yaml skill_years the years you are willing to state per skill

A skill named in the resume's experience bullets is evidence you can talk
about it for ten minutes. The same skill appearing only in a comma-separated
key_skills list is not. That difference is what decides Strong vs Moderate in
the skill matrix, so the loader keeps the provenance instead of flattening it.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("naukri.interview.profile")

ROOT = Path(__file__).resolve().parent.parent.parent
RESUME_DIR = ROOT / "resume"
PROFILE_JSON = ROOT / "data" / "profile.json"
JOBS_YAML = ROOT / "jobs.yaml"

# Resume headings whose bullets count as lived experience rather than a list.
NARRATIVE_HEADINGS = (
    "PROFESSIONAL SUMMARY", "PROFESSIONAL EXPERIENCE", "KEY PROJECTS",
    "WORK EXPERIENCE", "EXPERIENCE", "PROJECTS", "SUMMARY",
)
LIST_HEADINGS = ("TECHNICAL SKILLS", "SKILLS", "TOOLS", "TECHNOLOGIES")


class ProfileError(RuntimeError):
    """Raised when there is nothing to compare the JDs against."""


def resume_path() -> Path | None:
    """The plain-text resume. Prefers a *_Resume.txt, else any .txt."""
    named = sorted(RESUME_DIR.glob("*Resume*.txt"))
    if named:
        return named[0]
    any_txt = sorted(RESUME_DIR.glob("*.txt"))
    return any_txt[0] if any_txt else None


def _split_sections(text: str) -> dict[str, str]:
    """Split the resume on ALL-CAPS headings into {heading: body}."""
    sections, current, buffer = {}, "HEADER", []
    for line in text.splitlines():
        stripped = line.strip()
        is_heading = (
            stripped
            and len(stripped) < 60
            and stripped == stripped.upper()
            and re.search(r"[A-Z]{3}", stripped)
            and not stripped.startswith("-")
        )
        if is_heading:
            sections[current] = "\n".join(buffer).strip()
            current, buffer = stripped, []
        else:
            buffer.append(line)
    sections[current] = "\n".join(buffer).strip()
    return sections


def _years_from_yaml() -> dict[str, float]:
    if not JOBS_YAML.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(JOBS_YAML.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log.warning("jobs.yaml unreadable (%s); skill years unavailable", exc)
        return {}
    raw = data.get("skill_years") or {}
    out = {}
    for skill, years in raw.items():
        try:
            out[str(skill).strip().lower()] = float(years)
        except (TypeError, ValueError):
            continue
    return out


def _total_years(profile: dict) -> float | None:
    text = profile.get("experience") or ""
    match = re.search(r"(\d+)\s*year", text, re.I)
    if not match:
        return None
    years = float(match.group(1))
    months = re.search(r"(\d+)\s*month", text, re.I)
    if months:
        years += float(months.group(1)) / 12
    return round(years, 2)


def load() -> dict:
    """Everything about you that the analysis needs, with provenance kept."""
    path = resume_path()
    resume_text = path.read_text(encoding="utf-8") if path else ""
    if not resume_text:
        log.warning("No plain-text resume in %s - falling back to profile.json only. "
                    "Run: python resume/build_resume.py", RESUME_DIR)

    sections = _split_sections(resume_text)
    narrative = "\n".join(body for head, body in sections.items()
                          if any(h in head for h in NARRATIVE_HEADINGS))
    listed = "\n".join(body for head, body in sections.items()
                       if any(h in head for h in LIST_HEADINGS))

    profile_json = {}
    if PROFILE_JSON.exists():
        try:
            profile_json = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("profile.json unreadable (%s)", exc)

    if not resume_text and not profile_json:
        raise ProfileError(
            "No resume text and no data/profile.json - there is nothing to "
            "compare the job descriptions against.\n"
            "  Run:  python main.py --extract")

    key_skills = [s for s in (profile_json.get("key_skills") or []) if s]

    return {
        "name": profile_json.get("name") or "",
        "designation": profile_json.get("current_designation") or "",
        "location": profile_json.get("location") or "",
        "total_years": _total_years(profile_json),
        "resume_path": str(path) if path else None,
        "resume_text": resume_text,
        # Bullets from experience/projects - strong evidence.
        "narrative": narrative,
        # Comma-separated skill lines - weaker evidence.
        "listed_skills_text": listed,
        "key_skills": key_skills,
        "it_skills": profile_json.get("it_skills") or [],
        "summary": profile_json.get("profile_summary") or "",
        "headline": profile_json.get("resume_headline") or "",
        "certifications": profile_json.get("certifications") or [],
        "employment": profile_json.get("employment") or [],
        "skill_years": _years_from_yaml(),
    }


def brief(profile: dict, limit: int = 4200) -> str:
    """A compact profile blob to put in a prompt.

    The resume is the best single description of you that exists, so it goes in
    whole where it fits. Trimming is by section rather than mid-sentence - half
    a bullet in a prompt reads as a half-finished claim.
    """
    parts = []
    if profile.get("resume_text"):
        parts.append(profile["resume_text"].strip())
    else:
        parts.append(f"{profile['name']} - {profile['designation']}")
        if profile.get("summary"):
            parts.append(profile["summary"])
        if profile.get("key_skills"):
            parts.append("Key skills: " + ", ".join(profile["key_skills"]))

    if profile.get("skill_years"):
        stated = ", ".join(f"{k} {v:g}y" for k, v in
                           sorted(profile["skill_years"].items(), key=lambda kv: -kv[1]))
        parts.append("Stated years per skill: " + stated)

    text = "\n\n".join(parts)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n[...truncated]"
