"""A resume tailored to one job description, in the same layout as your own.

    python -m naukri.jobs.tailor <job-description.txt> [--title "Backend Engineer"] [--company Acme]

Company-site applications upload this instead of the generic resume
(`tailor_resume: true` in jobs.yaml, the default). It is printed by
resume/build_resume.py from a tailored copy of resume/resume.yaml as a PDF laid
out like your own resume (same fonts, spacing, sections, bold metrics, links);
only the content is arranged for the job:

  - every skill the job asks for that you have is on the page, in the job's own
    words: when the posting says "RESTful" and your resume "REST APIs", the line
    reads "REST APIs (RESTful)";
  - a skill the job asks for that is only in `extra_skills` (skills you have but
    keep off the generic resume) is added to its group, for this job only;
  - the title line leads with the job's role when that is honestly your role
    (never a lead / senior / test title, never a technology you do not have),
    then your strongest matching skills;
  - skills lines, the tech line under each role and project, and every list of
    bullets put what the job asks for first;
  - the summary is rewritten by the local model to lead with the job's needs.

It never claims anything your resume does not. Skills the job wants that you do
not have are reported (`missing`), not added; the rewrite may only name skills
already in resume.yaml and must keep every number in your summary, or your own
summary is kept. So the keyword match it reports is the honest one.

It stays one page like the original: first a few percent smaller, then the
bullets that matter least for THIS job go (never below 7 bullets in a role or 2
in a project). Files land in data/jobs/tailored/ and are kept, so you can see
exactly what each employer received.
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
TECH_TITLE = re.compile(r"engineer|developer|sde|programmer|backend|frontend|full.?stack|software", re.I)
# A title line you could not defend: a level above yours, or a different job.
NOT_YOUR_TITLE = re.compile(r"\b(?:senior|sr|lead|staff|principal|manager|head|director|architect|chief|vp|president|"
                            r"intern|internship|trainee|test|testing|qa|sdet|quality|deployment|support|sales|solutions?|"
                            r"consultant|analyst|data|ml|ai|devops|sre|security|embedded|firmware|hardware|mobile|"
                            r"android|ios)\b", re.I)
MIN_BULLETS = {"experience": 7, "projects": 2}


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


def _plain(text) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or ""), flags=re.S)


def _flatten(data: dict) -> str:
    parts = [data.get("title", ""), data.get("summary", "")]
    for g in data.get("skills") or []:
        parts.append(f"{g.get('label', '')}: {g.get('items', '')}")
    for key in ("experience", "projects"):
        for e in data.get(key) or []:
            parts += [e.get(k, "") for k in ("title", "org", "name", "label", "tech", "description")]
            parts += list(e.get("bullets") or [])
    parts += [str(c) for c in data.get("certifications") or []]
    return _plain("\n".join(str(p) for p in parts if p))


def _hits(text: str, skills, vocab) -> int:
    """How much of the job a line covers: skills found in it, each weighted by how often the job names it
    when `skills` is a {skill: weight} mapping."""
    found = vocab.find(_plain(text))
    return sum(skills[s] if isinstance(skills, dict) else 1 for s in skills if s in found)


def _split(items: str) -> list[str]:
    return [p.strip() for p in re.split(r",(?![^()]*\))", items or "") if p.strip()]


def _display(skill: str, data: dict, vocab=None) -> str:
    """The skill as your resume writes it ("rest api" -> "REST APIs", "spring" -> "Spring Boot")."""
    items = [re.sub(r"\s*\(.*?\)", "", p).strip() for g in data.get("skills") or [] for p in _split(g.get("items", ""))]
    if vocab is not None:
        for it in items:
            if skill in vocab.find(it):
                return it
    words = skill.lower().split()
    for it in items:
        low = it.lower()
        if all(re.search(r"\b" + re.escape(w), low) for w in words):
            return it
    return skill.title() if len(skill) > 3 else skill.upper()


def jd_terms(jd: str, vocab) -> dict[str, list[str]]:
    """canonical skill -> the words the posting uses for it, most used first."""
    seen: dict[str, Counter] = {}
    for m in vocab.re.finditer(jd or ""):
        word = m.group(1).strip()
        seen.setdefault(vocab.canon[word.lower()], Counter())[word] += 1
    return {canon: [w for w, _ in c.most_common()] for canon, c in seen.items()}


def headline_role(job_title: str, own_title: str, have: set, vocab) -> str:
    """The role on the title line: the job's, when it is honestly yours, else your own."""
    own = own_title.split("|")[0].strip()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", job_title or "")
    t = re.split(r"\s+[-–—|/]\s+|,|:", t)[0]
    t = re.sub(r"\b(?:[IVX]{1,3}|L?\d)\s*$", "", t.strip()).strip(" -")
    t = re.sub(r"\s+", " ", t)
    if (not t or len(t) > 40 or not TECH_TITLE.search(t) or NOT_YOUR_TITLE.search(t)
            or any(s not in have for s in vocab.find(t))):
        return own
    return t if t.isupper() or any(c.isupper() for c in t[1:]) else t.title()


def _add_extras(new: dict, wanted: set, vocab) -> list[str]:
    """Skills from `extra_skills` the job asks for, added to the group with the same label. -> added items."""
    added = []
    groups = new.setdefault("skills", [])
    for g in new.get("extra_skills") or []:
        label = str(g.get("label") or "Additional Skills")
        keep = [it for it in _split(str(g.get("items") or "")) if set(vocab.find(it)) & wanted]
        if not keep:
            continue
        target = next((x for x in groups if str(x.get("label", "")).lower() == label.lower()), None)
        if target is None:
            target = {"label": label, "items": ""}
            groups.insert(max(0, len(groups) - 1), target)          # before "Spoken"
        have_items = _split(target.get("items", ""))
        for it in keep:
            if it.lower() not in (h.lower() for h in have_items):
                have_items.append(it)
                added.append(it)
        target["items"] = ", ".join(have_items)
    return added


def _use_job_words(new: dict, terms: dict[str, list[str]], matched: list[str], vocab) -> list[str]:
    """Write the job's own word next to a skill the resume names differently. -> words added."""
    text = _flatten(new).lower()
    added = []
    for skill in matched:
        words = terms.get(skill) or []
        if not words or any(w.lower() in text for w in words):
            continue                                    # the posting's word is already on the page
        word = words[0]
        for g in new.get("skills") or []:
            items = _split(g.get("items", ""))
            for i, it in enumerate(items):
                if skill in vocab.find(it):
                    items[i] = it[:-1] + f", {word})" if it.endswith(")") else f"{it} ({word})"
                    g["items"] = ", ".join(items)
                    added.append(word)
                    break
            else:
                continue
            break
    return added


def _drop_least_relevant(data: dict, matched: list[str], vocab) -> bool:
    """Remove the bullet that covers least of the job: project bullets before experience ones, and never
    below MIN_BULLETS. False when nothing is left to drop."""
    worst = None
    for key in ("projects", "experience"):
        for e in data.get(key) or []:
            bl = e.get("bullets") or []
            if len(bl) <= MIN_BULLETS[key]:
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
    """The local model's summary for this job, or None when it would claim something new or drop a number."""
    try:
        _vocab()                               # puts job-hunt/scripts on the path
        from jobbot import localai             # the shared local model (Qwen), see job-hunt
    except Exception:
        return None
    if not localai.available("llm"):
        return None
    own = _plain(summary)
    numbers = re.findall(r"\d[\d,.+%x]*", own)
    prompt = (f"Rewrite this resume summary for a {title} role in at most {max(2, own.count('.'))} sentences "
              f"and at most {int(len(own) * 1.15)} characters. Lead with these skills where the summary supports them: "
              f"{', '.join(wanted[:8])}. Keep every number exactly as written ({', '.join(numbers)}). Use only facts "
              f"already in the summary. Do not add any skill, tool, employer or number that is not in it. "
              f"Reply with the summary text only.\n\nSummary:\n{own}")
    out = localai.ask(prompt, max_tokens=240, temperature=0.2)
    if not out or not isinstance(out, str):
        return None
    out = re.sub(r"\s+", " ", out).strip().strip('"')
    if len(out) < 60 or len(out) > len(own) * 1.25 or not out.endswith("."):
        return None                                           # cut off or rambling
    if any(s not in allowed for s in vocab.find(out)):
        return None                                           # names a skill the resume does not have
    found = re.findall(r"\d[\d,.+%x]*", out)
    if any(n.rstrip(".,") not in resume_text for n in found) or any(n not in out for n in numbers):
        return None                                           # a new number, or one of yours lost
    for phrase in re.findall(r"\*\*(.+?)\*\*", summary):      # your bold metrics stay bold
        if phrase in out:
            out = out.replace(phrase, f"**{phrase}**", 1)
    return out


def tailor(job: dict, jd: str, *, use_model: bool = True, one_page: bool = True) -> tuple[Path | None, dict]:
    """Build the tailored resume for `job` ({title, company}) from its description `jd`.
    Returns (pdf path - or .docx when Chromium is unavailable - or None, {match, matched, missing, ...})."""
    br = _resume_module()
    try:
        data = br.load()
    except Exception as exc:
        log.warning("tailor: resume.yaml unavailable (%s)", exc)
        return None, {}
    vocab = _vocab()
    jd_sk = vocab.find(jd or "")
    if not jd_sk:
        return None, {"match": None, "matched": [], "missing": [], "why": "no skills recognised in the job description"}
    ranked = [s for s, _ in Counter(jd_sk).most_common()]
    terms = jd_terms(jd, vocab)

    new = copy.deepcopy(data)
    from_extra = _add_extras(new, set(ranked), vocab)
    new.pop("extra_skills", None)
    resume_text = _flatten(new)
    have = set(vocab.find(resume_text))
    matched = [s for s in ranked if s in have]
    missing = [s for s in ranked if s not in have]
    job_words = _use_job_words(new, terms, matched, vocab)
    in_title = set(vocab.find(job.get("title") or ""))
    # what the posting repeats matters most, and what its title names most of all
    weight = {s: jd_sk[s] + (3 if s in in_title else 0) for s in matched}

    title = (job.get("title") or "").strip()
    if matched:
        shown = list(dict.fromkeys(_display(s, new, vocab) for s in matched))
        new["title"] = f"{headline_role(title, data.get('title', ''), have, vocab)} | " + ", ".join(shown[:4])

    # skills: what the job asks for first, inside each group and across groups ("Spoken" stays last)
    def order_items(items: str) -> str:
        parts = _split(items)
        return ", ".join(sorted(parts, key=lambda p: (-_hits(p, weight, vocab), parts.index(p))))
    groups = new.get("skills") or []
    for g in groups:
        g["items"] = order_items(g.get("items", ""))
    def top(items: str) -> int:                    # a group leads by its most wanted skill, not by its length
        return max((_hits(p, weight, vocab) for p in _split(items)), default=0)
    new["skills"] = sorted(groups, key=lambda g: (str(g.get("label", "")).lower() == "spoken", -top(g.get("items", "")),
                                                  -_hits(g.get("items", ""), weight, vocab), groups.index(g)))

    # bullets and tech lines: the ones covering most of the job first (roles stay in date order)
    for key in ("experience", "projects"):
        for e in new.get(key) or []:
            bl = list(e.get("bullets") or [])
            e["bullets"] = sorted(bl, key=lambda b: (-_hits(b, weight, vocab), bl.index(b)))
            if e.get("tech"):
                e["tech"] = order_items(e["tech"])
        if key == "projects" and new.get(key):
            items = new[key]
            new[key] = sorted(items, key=lambda e: (-_hits(_flatten({"projects": [e]}), weight, vocab), items.index(e)))

    rewritten = _rewrite_summary(data.get("summary", ""), have, matched, title or "software engineer",
                                 resume_text, vocab) if use_model and data.get("summary") else None
    if rewritten:
        new["summary"] = rewritten

    OUT.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{job.get('company', '')}-{title}".lower()).strip("-")[:60] or "job"
    stem = OUT / f"{time.strftime('%Y%m%d')}-{slug}"
    shrink = (lambda d: _drop_least_relevant(d, weight, vocab)) if one_page else None
    try:
        path, pages, dropped = br.build_pdf(new, stem.with_suffix(".pdf"), shrink=shrink)
    except Exception as exc:  # noqa: BLE001 - no Chromium: the .docx in the same layout still works
        log.warning("tailor: PDF failed (%s), uploading a .docx instead", exc)
        saved_out = br.OUT
        try:
            br.OUT = OUT                       # build into data/jobs/tailored, never over your own resume
            built = br.build(new)
        finally:
            br.OUT = saved_out
        path, pages, dropped = stem.with_suffix(".docx"), None, 0
        if path.exists():
            path.unlink()
        built.rename(path)

    info = {"match": round(100 * len(matched) / len(ranked)), "matched": matched, "missing": missing,
            "added_from_extra_skills": from_extra, "job_words_added": job_words,
            "summary_rewritten": bool(rewritten), "file": str(path), "pages": pages, "bullets_dropped": dropped}
    log.info("tailored resume %s: %d%% of the job's skills (%d/%d)%s", path.name, info["match"], len(matched), len(ranked),
             f"; not on your resume: {', '.join(missing[:6])}" if missing else "")
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
    print(f"not on your resume (not added): {', '.join(info.get('missing') or []) or 'nothing'}")
    if info.get("job_words_added"):
        print(f"the job's own words added: {', '.join(info['job_words_added'])}")
    if info.get("added_from_extra_skills"):
        print(f"from extra_skills: {', '.join(info['added_from_extra_skills'])}")
    print(f"pages: {info.get('pages')}  (bullets dropped to fit: {info.get('bullets_dropped')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
