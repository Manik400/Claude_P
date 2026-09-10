"""Experience requirement parsing and fit classification."""
import re

# numbers followed by a year word, in the languages of the supported countries
_YEAR_WORDS = r"(?:years?|yrs?|yr|jahren?|jahre|jaar|años|anos|anni|ans|vuotta|vuoden|år|lat|年|ปี)"
_NUM = r"(\d{1,2})(?:\s*(?:\+|plus))?"
_RANGE_RE = re.compile(
    rf"(?<![\d.])(?:{_NUM}\s*(?:-|–|—|to|bis|a|tot|/|~)\s*)?(\d{{1,2}})\s*\+?\s*{_YEAR_WORDS}",
    re.I,
)
# context words that indicate the number refers to professional experience
_CONTEXT = re.compile(
    r"experience|exp\b|erfahrung|berufserfahrung|ervaring|experiencia|kokemus|kokemusta|työkokemus|経験|"
    r"expérience|esperienza|erfarenhet|doświadczenie|ประสบการณ์|track record|background in|hands-on|hands on|"
    r"in a similar role|professional|industry|proven|minimum|at least|mindestens|min\.|mín|minimo|mínimo|"
    r"working with|working as|developing|programming|coding|engineering",
    re.I,
)

_SENIORITY = [
    ("intern", (0, 0), r"\b(intern|internship|praktikant|praktikum|werkstudent|working student|stagiair|becario|harjoittelija|インターン|trainee)\b"),
    ("junior", (0, 2), r"\b(junior|jr\.?|graduate|entry[- ]level|early career|associate|nuori|absolvent|recién|新卒|ジュニア)\b"),
    ("mid", (2, 5), r"\b(mid|mid-level|medior|intermediate|regular)\b"),
    ("senior", (5, None), r"\b(senior|sr\.?|experienced|erfahren|シニア|expert)\b"),
    ("lead", (7, None), r"\b(lead|leader|principal|staff|head of|architect|manager|director|vp|chief|teamlead|team lead|cto)\b"),
]


def parse_experience(text):
    """Return (min_years, max_years) found in text, or (None, None)."""
    if not text:
        return None, None
    best = None
    for m in _RANGE_RE.finditer(text):
        lo_s, hi_s = m.group(1), m.group(2)
        window = text[max(0, m.start() - 90): m.end() + 60]
        if not _CONTEXT.search(window):
            continue
        hi = int(hi_s)
        lo = int(lo_s) if lo_s else hi
        if lo > hi:
            lo, hi = hi, lo
        if hi > 25 or lo > 25:
            continue
        plus = bool(re.search(r"\+|plus|at least|minimum|mindestens|min\.|mínimo|minimo|mínima|minima|al menos|minstens|"
                              r"vähintään|or more|oder mehr|of meer|o más|以上", window, re.I))
        rng = (float(lo), None if (plus and not lo_s) else float(hi))
        if lo_s is None and plus:
            rng = (float(hi), None)
        # keep the first strong match; prefer explicit ranges
        if best is None or (best[1] is None and rng[1] is not None and lo_s):
            best = rng
    return best if best else (None, None)


def seniority_from_title(title):
    t = " " + (title or "").lower() + " "
    found = None
    for name, rng, pat in _SENIORITY:
        if re.search(pat, t, re.I):
            found = (name, rng)
            # do not break: a later, more senior marker wins ("Senior Lead Engineer")
    return found  # (name, (min, max)) or None


def classify_fit(user_years, exp_min, exp_max, seniority):
    """fit / stretch / over / no / unknown for a candidate with `user_years` experience."""
    if user_years is None:
        return "unknown"
    lo, hi = exp_min, exp_max
    if lo is None and hi is None and seniority:
        lo, hi = seniority[1]
        if seniority[0] == "intern" and user_years > 1:
            return "over"
    if lo is None and hi is None:
        return "unknown"
    lo = lo or 0
    if user_years >= lo:
        if hi is None or user_years <= hi + 2:
            return "fit"
        if user_years <= hi + 5:
            return "over"
        return "over"
    gap = lo - user_years
    return "stretch" if gap <= 2 else "no"


def annotate(job, user_years):
    """Fill exp_min/exp_max/seniority/fit on a Job in place."""
    text = " ".join([job.title or "", job.snippet or "", job.description or ""])
    lo, hi = parse_experience(text)
    # some platforms give structured values
    if job.exp_min is None and job.exp_max is None:
        job.exp_min, job.exp_max = lo, hi
    sen = seniority_from_title(job.title)
    job.seniority = sen[0] if sen else (job.seniority or "")
    job.fit = classify_fit(user_years, job.exp_min, job.exp_max, sen)
    return job


def parse_user_experience(value):
    """'3' -> 3.0 ; '2-4' -> 3.0 (midpoint) ; '5+' -> 5.0 ; None -> None"""
    if value is None:
        return None
    s = str(value).strip().lower().replace("years", "").replace("yrs", "").replace("year", "").strip()
    m = re.match(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)", s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    m = re.match(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def linkedin_experience_codes(user_years):
    """LinkedIn f_E codes: 1 intern, 2 entry, 3 associate, 4 mid-senior, 5 director, 6 executive."""
    if user_years is None:
        return None
    if user_years < 1:
        return "1,2"
    if user_years < 3:
        return "2,3"
    if user_years < 6:
        return "3,4"
    if user_years < 10:
        return "4"
    return "4,5"
