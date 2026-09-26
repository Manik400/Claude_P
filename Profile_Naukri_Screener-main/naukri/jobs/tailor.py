"""A resume tailored to one job description, in the same layout as your own.

    python -m naukri.jobs.tailor <job-description.txt> [--title "Backend Engineer"] [--company Acme]

Company-site applications upload this instead of the generic resume
(`tailor_resume: true` in jobs.yaml, the default). It is built by
resume/build_resume.py from a tailored copy of resume/resume.yaml, so fonts,
spacing and section order stay exactly those of your resume; only the content
is arranged for the job:

  - the title line leads with the job's role and your strongest matching skills;
  - every skills line lists the skills the job asks for first, and the skill
    groups the job cares about most come first;
  - experience and project bullets are ordered by how much of the job they cover;
  - the summary is rewritten by the local model to lead with the job's needs.

It never claims anything your resume does not. The rewrite may only name skills
already in resume.yaml and numbers already in it; a rewrite that adds anything
else is thrown away and your own summary is kept. So the keyword match it
reports is the honest one: the share of the job's skills your resume really
has, plus the ones you are missing (worth learning, or adding to resume.yaml if
you do have them).

Files land in data/jobs/tailored/ and are kept, so you can see exactly what
each employer received.
"""
from __future__ import annotations

import copy
import logging
import re
import sys
import time
from collections import Counter
from pathlib import Path

log = logging.getLogger("naukri.jobs.tailor")

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "data" / "jobs" / "tailored"
TECH_TITLE = re.compile(r"engineer|developer|sde|programmer|architect|backend|frontend|full.?stack|devops|software", re.I)


def _vocab():
    here = ROOT.parent / "job-hunt" / "scripts"
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from jobbot.scoring import Vocab   # the project's skill vocabulary (synonyms folded to one name)
    return Vocab()


def _resume_module():
    here = ROOT / "resume"
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import build_resume
    return build_resume


def _flatten(data: dict) -> str:
    parts = [data.get("title", ""), data.get("summary", "")]
    for g in data.get("skills") or []:
        parts.append(f"{g.get('label', '')}: {g.get('items', '')}")
    for key in ("experience", "projects"):
        for e in data.get(key) or []:
            parts += [e.get("title", ""), e.get("org", "")] + list(e.get("bullets") or [])
    return "\n".join(str(p) for p in parts if p)


def _hits(text: str, skills: list[str], vocab) -> int:
    found = vocab.find(text)
    return sum(1 for s in skills if s in found)


def _display(skill: str, data: dict) -> str:
    """The skill as your resume writes it ("rest api" -> "REST APIs", "spring" -> "Spring Boot")."""
    items = [re.sub(r"\s*\(.*?\)", "", p).strip() for g in data.get("skills") or []
             for p in re.split(r",(?![^()]*\))", g.get("items", "")) if p.strip()]
    words = skill.lower().split()
    for it in items:
        low = it.lower()
        if all(re.search(r"\b" + re.escape(w), low) for w in words):
            return it
    return skill.title() if len(skill) > 3 else skill.upper()


def _pages(path: Path) -> int | None:
    """Pages Word lays the document out on (Windows with Word installed), else None."""
    import subprocess
    ps = ("$w = New-Object -ComObject Word.Application; try { $d = $w.Documents.Open('%s', $false, $true); "
          "$d.ComputeStatistics(2); $d.Close($false) } finally { $w.Quit() }") % str(path).replace("'", "''")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=90)
        return int(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def _drop_least_relevant(data: dict, matched: list[str], vocab) -> bool:
    """Remove the bullet that covers least of the job (never below 2 bullets in a role). False when nothing is left to drop."""
    worst = None
    for key in ("projects", "experience"):
        for e in data.get(key) or []:
            bl = e.get("bullets") or []
            if len(bl) <= 2:
                continue
            for i, b in enumerate(bl):
                cand = (_hits(b, matched, vocab), key == "experience", -i)
                if worst is None or cand < worst[0]:
                    worst = (cand, e, i)
    if worst is None:
        return False
    worst[1]["bullets"].pop(worst[2])
    return True


def _rewrite_summary(summary: str, allowed: set[str], wanted: list[str], title: str, resume_text: str, vocab) -> str | None:
    """The local model's summary for this job, or None when it would claim something new."""
    try:
        _vocab()                               # puts job-hunt/scripts on the path
        from jobbot import localai             # the shared local model (Qwen), see job-hunt
    except Exception:
        return None
    if not localai.available("llm"):
        return None
    prompt = (f"Rewrite this resume summary for a {title} role in at most {max(2, summary.count('.'))} sentences "
              f"and at most {int(len(summary) * 1.1)} characters. Lead with these skills where the summary supports them: "
              f"{', '.join(wanted[:8])}. Use only facts and numbers already in the summary. Do not add any skill, tool, "
              f"employer or number that is not in it. Reply with the summary text only.\n\nSummary:\n{summary}")
    out = localai.ask(prompt, max_tokens=220, temperature=0.2)
    if not out or not isinstance(out, str):
        return None
    out = re.sub(r"\s+", " ", out).strip().strip('"')
    if len(out) < 60 or len(out) > len(summary) * 1.25:
        return None
    if any(s not in allowed for s in vocab.find(out)):
        return None                                           # names a skill the resume does not have
    if any(n not in resume_text for n in re.findall(r"\d[\d,.+%]*", out)):
        return None                                           # a number that is not in the resume
    return out


def tailor(job: dict, jd: str, *, use_model: bool = True, one_page: bool = True) -> tuple[Path | None, dict]:
    """Build the tailored resume for `job` ({title, company}) from its description `jd`.
    Returns (docx path or None, {match, matched, missing, ...})."""
    br = _resume_module()
    try:
        data = br.load()
    except Exception as exc:
        log.warning("tailor: resume.yaml unavailable (%s)", exc)
        return None, {}
    vocab = _vocab()
    resume_text = _flatten(data)
    jd_sk = vocab.find(jd or "")
    have = vocab.find(resume_text)
    if not jd_sk:
        return None, {"match": None, "matched": [], "missing": [], "why": "no skills recognised in the job description"}
    ranked = [s for s, _ in Counter(jd_sk).most_common()]
    matched = [s for s in ranked if s in have]
    missing = [s for s in ranked if s not in have]

    new = copy.deepcopy(data)
    title = (job.get("title") or "").strip()
    if title and TECH_TITLE.search(title) and matched:
        shown = list(dict.fromkeys(_display(s, data) for s in matched))
        new["title"] = f"{title} | " + ", ".join(shown[:4])

    # skills: what the job asks for first, inside each group and across groups
    def order_items(items: str) -> str:
        parts = [p.strip() for p in re.split(r",(?![^()]*\))", items or "") if p.strip()]
        return ", ".join(sorted(parts, key=lambda p: (-_hits(p, matched, vocab), parts.index(p))))
    groups = new.get("skills") or []
    for g in groups:
        g["items"] = order_items(g.get("items", ""))
    new["skills"] = sorted(groups, key=lambda g: (-_hits(g.get("items", ""), matched, vocab), groups.index(g)))

    # bullets: the ones covering most of the job first (experience entries stay in date order)
    for key in ("experience", "projects"):
        for e in new.get(key) or []:
            bl = list(e.get("bullets") or [])
            e["bullets"] = sorted(bl, key=lambda b: (-_hits(b, matched, vocab), bl.index(b)))
        if key == "projects" and new.get(key):
            items = new[key]
            new[key] = sorted(items, key=lambda e: (-_hits(_flatten({"projects": [e]}), matched, vocab), items.index(e)))

    rewritten = _rewrite_summary(data.get("summary", ""), set(have), matched, title or "software engineer",
                                 resume_text, vocab) if use_model and data.get("summary") else None
    if rewritten:
        new["summary"] = rewritten

    OUT.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{job.get('company', '')}-{title}".lower()).strip("-")[:60] or "job"
    path = OUT / f"{time.strftime('%Y%m%d')}-{slug}.docx"
    dropped, pages = 0, None
    for _attempt in range(10):
        saved_out = br.OUT
        try:
            br.OUT = OUT                       # build into data/jobs/tailored, never over your own resume
            built = br.build(new)
        finally:
            br.OUT = saved_out
        if path.exists():
            path.unlink()
        built.rename(path)
        # one page: drop the bullets that matter least for THIS job until Word says it fits
        pages = _pages(path) if one_page else 1
        if pages is None or pages <= 1 or not _drop_least_relevant(new, matched, vocab):
            break
        dropped += 1
    info = {"match": round(100 * len(matched) / len(ranked)), "matched": matched, "missing": missing,
            "summary_rewritten": bool(rewritten), "file": str(path), "pages": pages, "bullets_dropped": dropped}
    log.info("tailored resume %s: %d%% of the job's skills (%d/%d)%s", path.name, info["match"], len(matched), len(ranked),
             f"; missing {', '.join(missing[:6])}" if missing else "")
    return path, info


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jd_file")
    ap.add_argument("--title", default="Software Engineer")
    ap.add_argument("--company", default="")
    ap.add_argument("--no-model", action="store_true")
    a = ap.parse_args(argv)
    jd = Path(a.jd_file).read_text(encoding="utf-8")
    path, info = tailor({"title": a.title, "company": a.company}, jd, use_model=not a.no_model)
    print(path)
    print(f"match {info.get('match')}%  matched: {', '.join(info.get('matched') or [])}")
    print(f"missing: {', '.join(info.get('missing') or []) or 'nothing'}")
    print(f"pages: {info.get('pages')}  (bullets dropped to fit: {info.get('bullets_dropped')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
