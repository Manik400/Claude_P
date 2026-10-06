"""Salary text -> rupees a year, so a run can keep only postings that pay at least X.

Boards and descriptions write pay in every shape there is: "4-6 LPA", "₹4,00,000 -
6,00,000 P.A.", "CTC 8 Lakhs", "$120k-$150k", "€60.000 – €75.000 per year",
"£45,000 per annum", "AED 15,000 per month", "S$6,000/month", "$45 per hour".
parse() reads one such phrase; find_in_text() finds the first phrase in a job
description that is really about pay (a currency or a word like CTC / LPA /
salary next to the number, so "5+ years" and "2025" are never read as money).

Everything is converted to INR per year with the fixed rates below. They are
rounded, deliberately: the floor is "about ten lakh", not an accounting figure,
and a job stated in dollars clears a ten-lakh floor by a mile either way.
JOBHUNT_FX_JSON (a JSON object of code -> rupees per unit) overrides them.

A posting that states no salary is not "below the floor" - nobody knows what it
pays - so callers keep it and mark it `salary_stated: false`.
"""
import json
import os
import re

# rupees per one unit of the currency (approximate, mid-2026)
RATES_TO_INR = {
    "INR": 1.0, "USD": 84.0, "EUR": 92.0, "GBP": 108.0, "AUD": 56.0, "CAD": 61.0, "SGD": 64.0, "AED": 23.0,
    "JPY": 0.56, "THB": 2.5, "CHF": 95.0, "SEK": 8.1, "NOK": 7.9, "DKK": 12.3, "PLN": 21.0, "MYR": 19.0,
    "HKD": 10.8, "NZD": 51.0, "KRW": 0.062, "CZK": 3.6, "HUF": 0.23, "ILS": 23.0, "ZAR": 4.6, "BRL": 15.0,
    "MXN": 4.3, "PHP": 1.5, "IDR": 0.0053, "VND": 0.0033, "TRY": 2.4, "SAR": 22.0, "QAR": 23.0, "CNY": 11.6,
    "TWD": 2.6, "RON": 18.5, "BGN": 47.0, "EGP": 1.7, "PKR": 0.3, "BDT": 0.7, "LKR": 0.28, "NGN": 0.055,
}
try:
    RATES_TO_INR.update({str(k).upper(): float(v) for k, v in json.loads(os.environ.get("JOBHUNT_FX_JSON") or "{}").items()})
except (ValueError, TypeError, AttributeError):
    pass

LAKH = 100_000
CRORE = 10_000_000

# Symbols / codes -> ISO code. Longer keys first when matching.
_CURRENCY_WORDS = [
    ("₹", "INR"), ("rs.", "INR"), ("rs ", "INR"), ("inr", "INR"), ("rupees", "INR"),
    ("us$", "USD"), ("usd", "USD"), ("a$", "AUD"), ("au$", "AUD"), ("aud", "AUD"), ("c$", "CAD"), ("ca$", "CAD"), ("cad", "CAD"),
    ("s$", "SGD"), ("sgd", "SGD"), ("nz$", "NZD"), ("nzd", "NZD"), ("hk$", "HKD"), ("hkd", "HKD"), ("mx$", "MXN"), ("r$", "BRL"),
    ("$", "USD"), ("€", "EUR"), ("eur", "EUR"), ("euro", "EUR"), ("euros", "EUR"), ("£", "GBP"), ("gbp", "GBP"),
    ("aed", "AED"), ("dhs", "AED"), ("dirham", "AED"), ("¥", "JPY"), ("jpy", "JPY"), ("yen", "JPY"), ("฿", "THB"), ("thb", "THB"), ("baht", "THB"),
    ("chf", "CHF"), ("sek", "SEK"), ("kr", "SEK"), ("nok", "NOK"), ("dkk", "DKK"), ("pln", "PLN"), ("zł", "PLN"), ("zl", "PLN"),
    ("myr", "MYR"), ("rm", "MYR"), ("krw", "KRW"), ("₩", "KRW"), ("czk", "CZK"), ("kč", "CZK"), ("huf", "HUF"), ("ils", "ILS"), ("₪", "ILS"),
    ("zar", "ZAR"), ("brl", "BRL"), ("mxn", "MXN"), ("php", "PHP"), ("idr", "IDR"), ("vnd", "VND"), ("try", "TRY"), ("sar", "SAR"),
    ("qar", "QAR"), ("cny", "CNY"), ("rmb", "CNY"), ("twd", "TWD"), ("ron", "RON"), ("egp", "EGP"), ("pkr", "PKR"), ("bdt", "BDT"), ("lkr", "LKR"),
]
def _cur_pattern(word):
    # letters need word edges ("rm" must not match inside "platform"); symbols stand alone
    if re.search(r"[a-z]", word):
        return r"(?<![a-z])" + re.escape(word) + r"(?![a-z])"
    return re.escape(word)


_CURRENCY_RX = re.compile("|".join(_cur_pattern(w) for w, _ in sorted(_CURRENCY_WORDS, key=lambda x: -len(x[0]))), re.I)
_CODE_OF = {w: c for w, c in _CURRENCY_WORDS}
# a number that is about time or people, not money
_NOT_MONEY_TAIL = re.compile(r"^\s*\+?\s*(?:years?|yrs?|yoe|y\b|months?\s+of|experience|exp\b|batch|pass|employees|people|engineers|members|"
                             r"team|hours?\s+(?:a|per)\s+week|days?\s+(?:a|per)\s+week|%|percent|st\b|nd\b|rd\b|th\b|:\d|am\b|pm\b)", re.I)

# a number with thousands separators of either style, an optional decimal part and an optional k / L / lakh / cr suffix
_NUM = r"(\d{1,3}(?:[,.]\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k\b|m\b|mn\b|million|lakhs?\b|lacs?\b|lpa\b|lac\b|l\b|crores?\b|cr\b)?"
_RANGE_RX = re.compile(rf"{_NUM}(?:\s*(?:-|–|—|to|and|/)\s*(?:[₹$€£]|rs\.?|inr|usd|eur|gbp)?\s*{_NUM})?", re.I)
_PER_RX = re.compile(r"(?:per|/|an?|p\.?)\s*(annum|year|yr|month|mo|mth|week|wk|hour|hr|day|a\.?)\b|\b(p\.?a\.?|pa|pm|p\.m\.|yearly|annual(?:ly)?|monthly|hourly|weekly)\b", re.I)
_PAY_WORDS = re.compile(r"\b(ctc|lpa|lakh|lacs?|salary|package|compensation|pay\b|stipend|remuneration|per annum|p\.a\.|in[- ]hand|take[- ]home|base pay|total comp|otc|budget)\b", re.I)


class Salary:
    """One reading of a salary phrase, in rupees a year."""

    __slots__ = ("min_inr", "max_inr", "currency", "period", "text", "stated_annual")

    def __init__(self, min_inr, max_inr, currency, period, text):
        self.min_inr = min_inr
        self.max_inr = max_inr
        self.currency = currency
        self.period = period
        self.text = text

    @property
    def top_inr(self):
        """The most it says it pays - what a floor is compared against, so 8-12 LPA clears a 10 LPA floor."""
        return self.max_inr if self.max_inr is not None else self.min_inr

    def meets(self, floor_inr):
        return floor_inr is None or floor_inr <= 0 or (self.top_inr is not None and self.top_inr >= floor_inr)

    def to_dict(self):
        return {"min_inr": self.min_inr, "max_inr": self.max_inr, "currency": self.currency, "period": self.period,
                "text": self.text, "lpa": round(self.top_inr / LAKH, 1) if self.top_inr else None}

    def __repr__(self):
        return f"Salary({self.min_inr}, {self.max_inr}, {self.currency}, {self.period}, {self.text!r})"


def _to_float(s):
    s = s.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):      # 60.000 (European thousands)
        return float(s.replace(".", ""))
    if re.fullmatch(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?", s):   # 4,00,000 / 120,000 / 120,000.50
        return float(s.replace(",", ""))
    try:
        return float(s)
    except ValueError:
        return None


def _scale(value, unit):
    u = (unit or "").lower().rstrip(".")
    if not u:
        return value
    if u in ("k",):
        return value * 1_000
    if u in ("m", "mn", "million"):
        return value * 1_000_000
    if u.startswith("lakh") or u.startswith("lac") or u in ("l", "lpa"):
        return value * LAKH
    if u.startswith("cr"):
        return value * CRORE
    return value


def _period_of(text, unit_hint):
    """year | month | week | hour | day, from "per month" / "/yr" / "p.a." / "monthly" (default year)."""
    if unit_hint and unit_hint.lower().rstrip(".") in ("lpa",):
        return "year"
    m = _PER_RX.search(text)
    if not m:
        return "year"
    word = (m.group(1) or m.group(2) or "").lower().rstrip(".")
    if word.startswith(("month", "mo", "mth", "pm", "p.m")):
        return "month"
    if word.startswith(("week", "wk")):
        return "week"
    if word.startswith(("hour", "hr")):
        return "hour"
    if word == "day":
        return "day"
    return "year"


_PER_YEAR = {"year": 1, "month": 12, "week": 52, "day": 240, "hour": 2080}


def _currency_of(text, default="INR"):
    hits = _CURRENCY_RX.findall(text)
    for h in hits:
        code = _CODE_OF.get(h.lower())
        if code:
            return code
    low = text.lower()
    if re.search(r"\b(lpa|lakh|lacs?|lac|crore|ctc|p\.a\.)\b", low):
        return "INR"
    return default


def parse(text, default_currency="INR"):
    """Read one salary phrase -> Salary, or None when there is no money in it.

    The currency comes from a symbol / code in the phrase; a phrase with none that
    talks in lakhs / LPA / CTC is rupees; otherwise `default_currency`.
    """
    if not text:
        return None
    t = str(text).strip()
    if not t or not re.search(r"\d", t):
        return None
    currency = _currency_of(t, default_currency)
    rate = RATES_TO_INR.get(currency, 1.0)
    for m in _RANGE_RX.finditer(t):
        if _NOT_MONEY_TAIL.match(t[m.end():m.end() + 24]):
            continue                                    # "0-2 years", "2025 batch", "40 hours per week"
        lo, lo_u, hi, hi_u = m.group(1), m.group(2), m.group(3), m.group(4)
        unit = hi_u or lo_u
        a = _to_float(lo)
        b = _to_float(hi) if hi else None
        if a is None:
            continue
        # "4-6 LPA": the unit after the second number applies to the first as well
        a = _scale(a, lo_u or unit)
        b = _scale(b, hi_u or unit) if b is not None else None
        if b is not None and b < a:
            a, b = b, a
        period = _period_of(t, unit)
        per_year = _PER_YEAR[period]
        # A bare small number in rupees with no unit ("40,000") is a monthly figure far more
        # often than a yearly one; one with a currency and no period under 500/yr can only be hourly.
        if currency == "INR" and period == "year" and not unit and a < 50_000 and not re.search(r"\b(p\.?a\.?|annum|year|yearly|lpa)\b", t, re.I):
            period, per_year = "month", 12
        if currency != "INR" and period == "year" and not unit and a < 500 and not re.search(r"\b(annum|year|yearly)\b", t, re.I):
            period, per_year = "hour", 2080
        min_inr = round(a * rate * per_year)
        max_inr = round(b * rate * per_year) if b is not None else None
        # sanity: a year's pay between ₹30,000 and ₹100 crore, else this number was not a salary
        if all(v is None or 30_000 <= v <= 100 * CRORE for v in (min_inr, max_inr)):
            return Salary(min_inr, max_inr, currency, period, t[:120])
    return None


def find_in_text(text, default_currency="INR", limit=20000):
    """The first phrase in a description that is about pay -> Salary, or None.

    Scans for a currency mark or a pay word and reads the numbers around it, so
    "3-5 years of experience" or "founded in 2015" never count as money.
    """
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text))[:limit]
    best = None
    for m in re.finditer(r"(?i)(?:ctc|lpa|lakh|lacs?|salary|package|compensation|stipend|remuneration|pay\s*(?:range|scale)?|budget|in[- ]hand|take[- ]home|base pay|total comp)\b|[₹$€£¥฿₩₪]|\b(?:inr|usd|eur|gbp|aed|sgd|aud|cad|chf|sek|nok|dkk|pln|myr|thb|jpy|rs\.?)\b", t):
        start = max(0, m.start() - 24)
        window = t[start:m.end() + 70]
        s = parse(window, default_currency)
        if s is None:
            continue
        # a currency symbol alone is weak evidence; a pay word near it (or a yearly / LPA figure) is strong
        strong = bool(_PAY_WORDS.search(window)) or s.currency != "INR" or (s.period == "year" and s.top_inr >= 2 * LAKH)
        if strong:
            return s
        best = best or s
    return best


def parse_floor(text):
    """A floor typed by a person -> rupees a year: "10 LPA", "10L", "1000000", "12 lakh", "$30k", "" -> None."""
    if text is None:
        return None
    t = str(text).strip()
    if not t or t in ("0", "0.0"):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        v = float(t)
        if v <= 0:
            return None
        return int(v * LAKH) if v < 1000 else int(v)    # "10" / "7.5" mean lakhs a year; "1000000" is rupees
    s = parse(t if re.search(r"[a-zA-Z₹$€£]", t) else t + " per annum")
    if s is None:
        return None
    return s.min_inr


def label(inr):
    """₹ figure for people: 1000000 -> "10 LPA", 450000 -> "4.5 LPA", 25000000 -> "2.5 Cr"."""
    if not inr:
        return ""
    if inr >= CRORE:
        return ("%.2f" % (inr / CRORE)).rstrip("0").rstrip(".") + " Cr"
    return ("%.1f" % (inr / LAKH)).rstrip("0").rstrip(".") + " LPA"


def annotate(job, floor_inr=None):
    """Read the job's salary (its own field first, then the description) into job.extra.

    Sets extra.salary_stated (bool), extra.salary_inr (top of the stated range, rupees a
    year) and extra.salary_lpa; returns (meets_floor, salary). An unstated salary meets
    every floor - the caller decides whether to keep those.
    """
    s = parse(job.salary) if getattr(job, "salary", "") else None
    if s is None:
        s = find_in_text(" ".join([getattr(job, "snippet", "") or "", getattr(job, "description", "") or ""]))
    extra = job.extra if isinstance(getattr(job, "extra", None), dict) else {}
    if s is None:
        extra["salary_stated"] = False
        extra.pop("salary_inr", None)
        extra.pop("salary_lpa", None)
        return True, None
    extra["salary_stated"] = True
    extra["salary_inr"] = s.top_inr
    extra["salary_lpa"] = round(s.top_inr / LAKH, 1)
    extra["salary_text"] = s.text
    if not getattr(job, "salary", ""):
        job.salary = s.text
    return s.meets(floor_inr), s
