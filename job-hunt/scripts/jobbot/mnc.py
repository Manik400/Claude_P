"""Which companies count as "MNC" - big tech, product multinationals, unicorns, finance /
HFT - and what each typically pays a 0-2-year engineer in India.

    from jobbot import mnc
    mnc.match("Amazon Development Centre India Pvt Ltd")   -> {"name": "Amazon", "tier": "bigtech", "lpa": (12, 28), ...}
    mnc.is_mnc("TCS")                                       -> True (tier "itservices")
    mnc.typical_lpa("Google India")                         -> (18, 32)
    mnc.as_json()                                           -> what the phone page loads as data/mnc.json

The list is job-hunt/assets/mnc.txt:   Name | aliases; separated | tier | lo-hi LPA | careers URL
Matching is on the normalised company name: lower case, punctuation gone, the legal /
geographic tail removed ("Pvt Ltd", "India", "Technologies", "Development Centre" ...).
A short alias ("SAP", "AMD") only matches as a whole word, so "Sapient" is not SAP.
"""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(HERE)), "assets", "mnc.txt")

TIERS = {
    "bigtech": "Big tech", "product": "Product MNC", "unicorn": "Unicorn / startup", "finance": "Finance / bank",
    "hft": "HFT / quant", "gcc": "MNC engineering centre", "itservices": "IT services MNC", "consulting": "Consulting",
}
_TAIL = re.compile(r"\b(?:private|pvt|limited|ltd|inc|incorporated|corp|corporation|company|co|llc|llp|plc|gmbh|ag|sa|bv|"
                   r"nv|technologies|technology|tech|software|solutions|services|labs|lab|group|global|international|"
                   r"india|indian|bharat|development|dev|centre|center|r&d|research|engineering|systems|digital|holdings|"
                   r"consulting|consultancy|worldwide|asia|apac|emea|usa|us|uk)\b")
_PUNCT = re.compile(r"[^a-z0-9&+ ]+")
# Names that are ordinary words match only the whole normalised name, never as a prefix:
# "Open Universities Australia" is not Open Financial, "Unity Small Finance Bank" is not Unity.
GENERIC = {"open", "clear", "jar", "slice", "porter", "target", "shell", "unity", "sea", "navi", "zeta", "setu", "jupiter",
           "fi", "pw", "db", "ea", "hp", "ti", "gen", "epic", "snap", "digit", "meta", "apple", "bain", "clear tax", "x corp",
           "glance", "slice fintech", "jar app", "sandisk", "comcast", "sony", "sabre", "visa", "lyft", "wayfair", "chewy"}


def norm(name: str) -> str:
    s = _PUNCT.sub(" ", (name or "").lower().replace("&amp;", "&"))
    s = re.sub(r"\s+", " ", s).strip()
    # strip the legal / geographic tail, however many words of it, but never the whole name
    words = s.split()
    while len(words) > 1 and _TAIL.fullmatch(words[-1]):
        words.pop()
    return " ".join(words)


class _List:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self.entries: list[dict] = []
        self.exact: dict[str, dict] = {}
        self._mtime = 0.0
        self._load()

    def _load(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        self.entries, self.exact = [], {}
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                cols = [c.strip() for c in line.split("|")]
                while len(cols) < 5:
                    cols.append("")
                name, aliases, tier, band, url = cols[:5]
                lo = hi = None
                m = re.match(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", band or "")
                if m:
                    lo, hi = float(m.group(1)), float(m.group(2))
                elif re.match(r"\d", band or ""):
                    lo = hi = float(re.match(r"(\d+(?:\.\d+)?)", band).group(1))
                keys = [norm(name)] + [norm(a) for a in aliases.split(";") if a.strip()]
                e = {"name": name, "tier": tier or "product", "lo": lo, "hi": hi, "url": url, "keys": [k for k in keys if k]}
                self.entries.append(e)
                for k in e["keys"]:
                    self.exact.setdefault(k, e)

    def match(self, company: str) -> dict | None:
        self._load()
        c = norm(company)
        if not c:
            return None
        if c in self.exact:
            return self.exact[c]
        # "amazon web services" matches "amazon"; "jpmorgan chase & co" matches "jpmorgan chase"; whole words only,
        # never for a generic word or a short abbreviation (those matched above, exactly, or not at all)
        best = None
        for key, e in self.exact.items():
            if key in GENERIC or len(key) < 5:
                continue
            if c.startswith(key + " ") or (" " in key and re.search(r"(^| )" + re.escape(key) + r"( |$)", c)):
                if best is None or len(key) > len(best[0]):
                    best = (key, e)
        return best[1] if best else None


_LIST: _List | None = None


def _list() -> _List:
    global _LIST
    if _LIST is None:
        _LIST = _List()
    return _LIST


def match(company: str) -> dict | None:
    """The list entry for this company (name, tier, lo, hi, url), or None."""
    e = _list().match(company)
    return None if e is None else {"name": e["name"], "tier": e["tier"], "lo": e["lo"], "hi": e["hi"], "url": e["url"]}


def is_mnc(company: str) -> bool:
    return match(company) is not None


def tier(company: str) -> str:
    e = match(company)
    return e["tier"] if e else ""


def typical_lpa(company: str) -> tuple[float, float] | None:
    """What this company typically pays a 0-2-year engineer in India (lakhs a year), or None."""
    e = match(company)
    if not e or e["lo"] is None:
        return None
    return (e["lo"], e["hi"] if e["hi"] is not None else e["lo"])


def entries() -> list[dict]:
    return [dict(e) for e in _list().entries]


def as_json() -> str:
    """data/mnc.json for the phone page: names, aliases (normalised), tier, band, url."""
    rows = [{"n": e["name"], "k": [k for k in e["keys"] if k not in GENERIC and len(k) >= 5],       # prefix / whole-word keys
             "x": [k for k in e["keys"] if k in GENERIC or len(k) < 5],                              # exact-only keys
             "t": e["tier"], "lo": e["lo"], "hi": e["hi"], "u": e["url"]} for e in _list().entries]
    return json.dumps({"tiers": TIERS, "tail": _TAIL.pattern, "companies": rows}, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:] or ["Amazon Development Centre India Pvt Ltd", "TCS", "Some Startup"]:
        print(f"{arg!r:50} -> {match(arg)}")
