"""Resume <-> job match scoring (no heavy dependencies).

Score (0-100) blends:
  * skill coverage  - share of the skills named in the job that also appear in the resume
  * text similarity - TF-IDF cosine between the resume and the job text
  * title alignment - share of the job title's content words that appear in the resume
  * experience fit  - from experience.classify_fit
"""
import math
import os
import re
from collections import Counter

from .textutil import content_tokens, strip_accents

FIT_SCORE = {"fit": 1.0, "stretch": 0.65, "unknown": 0.55, "over": 0.7, "no": 0.15}
_SINGLE_LETTER = re.compile(r"(?<![A-Za-z0-9+#./-])([CR])(?![A-Za-z0-9+#&./-])")


class Vocab:
    def __init__(self, path=None):
        path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "skills_vocab.txt")
        self.canon = {}      # alias(lower) -> canonical
        self.single = set()  # single-letter skills handled separately
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|") if p.strip()]
                canonical = parts[0]
                for alias in parts:
                    a = alias.lower()
                    if len(a) == 1:
                        self.single.add(a.upper())
                        self.canon[a] = canonical
                    else:
                        self.canon[a] = canonical
        aliases = sorted((a for a in self.canon if len(a) > 1), key=len, reverse=True)
        pattern = "|".join(re.escape(a) for a in aliases)
        self.re = re.compile(r"(?<![a-z0-9+#])(" + pattern + r")(?![a-z0-9+#]|\.[a-z])", re.I)

    def find(self, text):
        """Counter of canonical skills found in text."""
        found = Counter()
        if not text:
            return found
        t = strip_accents(text)
        for m in self.re.finditer(t):
            found[self.canon[m.group(1).lower()]] += 1
        for m in _SINGLE_LETTER.finditer(t):
            letter = m.group(1)
            if letter in self.single:
                found[self.canon[letter.lower()]] += 1
        return found


def _tfidf_vectors(docs):
    """docs: list of token lists. Returns list of {term: weight} with idf."""
    n = len(docs)
    df = Counter()
    for toks in docs:
        for term in set(toks):
            df[term] += 1
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    vecs = []
    for toks in docs:
        tf = Counter(toks)
        v = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(w * w for w in v.values())) or 1.0
        vecs.append({t: w / norm for t, w in v.items()})
    return vecs


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def score_jobs(jobs, resume_text, vocab=None):
    """Annotate jobs in place with score / matched_skills / missing_skills. Returns summary dict."""
    vocab = vocab or Vocab()
    resume_skills = vocab.find(resume_text)
    resume_tokens = content_tokens(strip_accents(resume_text))
    resume_token_set = set(resume_tokens)
    docs = [resume_tokens] + [content_tokens(strip_accents(j.text_blob())) for j in jobs]
    vecs = _tfidf_vectors(docs)
    rvec = vecs[0]
    for j, jvec in zip(jobs, vecs[1:]):
        job_skills = vocab.find(" ".join([j.title, j.snippet, j.description]))
        for s in j.skills:  # platform-provided tags count as explicit requirements
            for c in vocab.find(s):
                job_skills[c] += 2
        matched = [s for s, _ in job_skills.most_common() if s in resume_skills]
        missing = [s for s, _ in job_skills.most_common() if s not in resume_skills]
        cos = _cos(rvec, jvec)
        cos_scaled = min(1.0, cos / 0.30)
        title_terms = [t for t in content_tokens(strip_accents(j.title)) if t not in ("developer", "engineer", "senior", "junior")]
        title_align = (sum(1 for t in title_terms if t in resume_token_set) / len(title_terms)) if title_terms else 0.0
        exp = FIT_SCORE.get(j.fit, 0.5)
        if len(job_skills) >= 2:
            cov = len(matched) / max(1, len(job_skills))
            # weight coverage by how much of the job's skill *mentions* the resume covers
            mention_cov = sum(c for s, c in job_skills.items() if s in resume_skills) / max(1, sum(job_skills.values()))
            cov = 0.5 * cov + 0.5 * mention_cov
            score = 100 * (0.45 * cov + 0.25 * cos_scaled + 0.15 * title_align + 0.15 * exp)
            confidence = "high" if len(j.description) > 400 else "medium"
        else:
            score = 100 * (0.45 * cos_scaled + 0.35 * title_align + 0.20 * exp)
            confidence = "low"
        j.score = round(max(0.0, min(100.0, score)), 1)
        j.matched_skills = matched[:12]
        j.missing_skills = missing[:8]
        j.extra["score_confidence"] = confidence
    return {
        "resume_skills": [s for s, _ in resume_skills.most_common(60)],
        "resume_chars": len(resume_text),
        "scored": len(jobs),
    }
