"""Location text -> ISO2 country codes.

Career pages list offices anywhere in the world, so this covers far more countries than the job-hunt
config. Only ever run it on short location strings ("Bangkok, Thailand", "London or Remote (UK)"),
never on descriptions: words like "us" would misfire in prose.
"""
import re

from ..config import COUNTRIES, COUNTRY_WORDS, REMOTE
from ..textutil import strip_accents

# Countries the job-hunt config does not cover: name, then country names / big tech cities (lower-case).
_EXTRA = {
    "IL": ("Israel", ["israel", "tel aviv", "tel-aviv", "jerusalem", "haifa", "herzliya", "yokneam", "petah tikva", "ra'anana"]),
    "CN": ("China", ["china", "shanghai", "beijing", "shenzhen", "guangzhou", "hangzhou", "chengdu", "suzhou", "nanjing"]),
    "TW": ("Taiwan", ["taiwan", "taipei", "hsinchu"]),
    "VN": ("Vietnam", ["vietnam", "viet nam", "ho chi minh", "hanoi", "da nang"]),
    "PH": ("Philippines", ["philippines", "manila", "makati", "taguig", "cebu", "quezon city"]),
    "ID": ("Indonesia", ["indonesia", "jakarta", "bali", "surabaya", "bandung"]),
    "PK": ("Pakistan", ["pakistan", "karachi", "lahore", "islamabad"]),
    "BD": ("Bangladesh", ["bangladesh", "dhaka"]),
    "LK": ("Sri Lanka", ["sri lanka", "colombo"]),
    "NP": ("Nepal", ["nepal", "kathmandu"]),
    "KZ": ("Kazakhstan", ["kazakhstan", "almaty", "astana"]),
    "UZ": ("Uzbekistan", ["uzbekistan", "tashkent"]),
    "TR": ("Turkey", ["turkey", "turkiye", "istanbul", "ankara", "izmir"]),
    "SA": ("Saudi Arabia", ["saudi arabia", "saudi", "riyadh", "jeddah", "ksa", "dammam"]),
    "QA": ("Qatar", ["qatar", "doha"]),
    "BH": ("Bahrain", ["bahrain", "manama"]),
    "KW": ("Kuwait", ["kuwait"]),
    "OM": ("Oman", ["oman", "muscat"]),
    "JO": ("Jordan", ["jordan", "amman"]),
    "EG": ("Egypt", ["egypt", "cairo", "alexandria"]),
    "MA": ("Morocco", ["morocco", "casablanca", "rabat"]),
    "ZA": ("South Africa", ["south africa", "cape town", "johannesburg", "durban", "pretoria"]),
    "NG": ("Nigeria", ["nigeria", "lagos", "abuja"]),
    "KE": ("Kenya", ["kenya", "nairobi"]),
    "GH": ("Ghana", ["ghana", "accra"]),
    "BR": ("Brazil", ["brazil", "brasil", "sao paulo", "rio de janeiro", "belo horizonte", "curitiba"]),
    "MX": ("Mexico", ["mexico", "mexico city", "ciudad de mexico", "guadalajara", "monterrey"]),
    "AR": ("Argentina", ["argentina", "buenos aires", "cordoba"]),
    "CO": ("Colombia", ["colombia", "bogota", "medellin"]),
    "CL": ("Chile", ["chile", "santiago de chile"]),
    "PE": ("Peru", ["peru", "lima"]),
    "UY": ("Uruguay", ["uruguay", "montevideo"]),
    "CR": ("Costa Rica", ["costa rica", "san jose, costa rica"]),
    "CZ": ("Czechia", ["czech republic", "czechia", "prague", "brno"]),
    "HU": ("Hungary", ["hungary", "budapest"]),
    "RO": ("Romania", ["romania", "bucharest", "cluj", "cluj-napoca", "iasi"]),
    "BG": ("Bulgaria", ["bulgaria", "sofia", "plovdiv"]),
    "GR": ("Greece", ["greece", "athens", "thessaloniki"]),
    "HR": ("Croatia", ["croatia", "zagreb", "split"]),
    "RS": ("Serbia", ["serbia", "belgrade", "novi sad"]),
    "SK": ("Slovakia", ["slovakia", "bratislava"]),
    "SI": ("Slovenia", ["slovenia", "ljubljana"]),
    "EE": ("Estonia", ["estonia", "tallinn", "tartu"]),
    "LV": ("Latvia", ["latvia", "riga"]),
    "LT": ("Lithuania", ["lithuania", "vilnius", "kaunas"]),
    "UA": ("Ukraine", ["ukraine", "kyiv", "kiev", "lviv", "kharkiv"]),
    "LU": ("Luxembourg", ["luxembourg"]),
    "CY": ("Cyprus", ["cyprus", "limassol", "nicosia", "larnaca"]),
    "MT": ("Malta", ["malta", "valletta"]),
    "IS": ("Iceland", ["iceland", "reykjavik"]),
    "GE": ("Georgia", ["tbilisi"]),  # "georgia" alone is usually the US state
    "AM": ("Armenia", ["armenia", "yerevan"]),
    "RU": ("Russia", ["russia", "moscow", "saint petersburg"]),
}

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
CA_PROVINCES = {"ON", "BC", "QC", "AB", "MB", "NS", "NB", "SK"}
AU_STATES = {"NSW", "VIC", "QLD", "ACT"}
_US_EXTRA = ["united states of america", "us", "usa", "u.s.", "palo alto", "mountain view", "sunnyvale", "san jose", "los angeles",
             "boston", "chicago", "denver", "atlanta", "miami", "washington", "bellevue", "redmond", "santa clara", "menlo park"]
_SHORT_OK = {"uk", "us", "uae", "usa", "ksa"}  # short words that are safe in location strings

NAMES = {code: m["name"] for code, m in COUNTRIES.items()}
NAMES.update({code: v[0] for code, v in _EXTRA.items()})
NAMES[REMOTE] = "Remote"


def _build():
    words = {}

    def add(code, w):
        w = strip_accents(w).strip().lower()
        if (len(w) > 3 or w in _SHORT_OK) and w not in words:
            words[w] = code

    for code, m in COUNTRIES.items():
        add(code, m["name"])
        for w in m["aliases"] + m["cities"]:
            add(code, w)
    for code, ws in COUNTRY_WORDS.items():
        for w in ws:
            add(code, w)
    for code, (name, ws) in _EXTRA.items():
        add(code, name)
        for w in ws:
            add(code, w)
    for w in _US_EXTRA:
        add("US", w)
    alts = sorted(words, key=len, reverse=True)
    rx = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in alts) + r")(?![a-z0-9])")
    return words, rx


_WORDS, _RX = _build()
_STATE_RX = re.compile(r",\s*([A-Z]{2,3})\b")
_REMOTE_RX = re.compile(r"\b(remote|anywhere|worldwide|work from home|wfh|distributed)\b", re.I)


def codes(*texts):
    """Ordered unique ISO2 codes named in the given location strings; [REMOTE] if only 'remote' is said."""
    out = []
    remote = False
    for text in texts:
        if not text:
            continue
        if isinstance(text, (list, tuple)):
            for c in codes(*text):
                if c not in out:
                    out.append(c)
            continue
        raw = str(text)
        low = strip_accents(raw).lower()
        for m in _RX.finditer(low):
            c = _WORDS[m.group(1)]
            if c not in out:
                out.append(c)
        for m in _STATE_RX.finditer(raw):
            s = m.group(1)
            c = "US" if s in US_STATES else "CA" if s in CA_PROVINCES else "AU" if s in AU_STATES else None
            if c and c not in out:
                out.append(c)
        if _REMOTE_RX.search(raw):
            remote = True
    if remote and not out:
        out.append(REMOTE)
    return out


def from_iso(value):
    """'gb' / 'GB' / 'UK' -> 'GB' when it is a code we know, else ''."""
    v = (value or "").strip().upper()
    if v == "UK":
        v = "GB"
    return v if v in NAMES and v != REMOTE else ""


def resolve(text):
    """User input (name, alias or ISO2) -> ISO2; 'worldwide' -> '*'; unknown -> None."""
    t = strip_accents(text or "").strip().lower()
    if not t:
        return None
    if t in ("worldwide", "world", "all", "any", "anywhere", "*", "global"):
        return "*"
    if t == "remote":
        return REMOTE
    if from_iso(t):
        return from_iso(t)
    for code, name in NAMES.items():
        if t == name.lower():
            return code
    c = _WORDS.get(t)
    if c:
        return c
    found = codes(text)
    return found[0] if len(found) == 1 else None


def name(code):
    return NAMES.get(code, code)
