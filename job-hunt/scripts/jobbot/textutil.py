"""Text helpers: HTML -> text, tokenizing, date parsing, slugs."""
import html as htmlmod
import re
import unicodedata
from datetime import datetime, timedelta, timezone

try:
    from bs4 import BeautifulSoup  # noqa: F401
    HAVE_BS4 = True
except Exception:  # pragma: no cover
    HAVE_BS4 = False


def soup(markup, parser="html.parser"):
    from bs4 import BeautifulSoup
    return BeautifulSoup(markup or "", parser)


def html_to_text(markup):
    if not markup:
        return ""
    if "<" not in markup:
        return normalize_ws(htmlmod.unescape(markup))
    try:
        s = soup(markup)
        for t in s(["script", "style", "noscript"]):
            t.decompose()
        text = s.get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", markup)
    return normalize_ws(htmlmod.unescape(text))


def normalize_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


# tokens keep + # . inside words so c++, c#, .net, node.js survive
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]", re.I)
STOPWORDS = {
    "and", "or", "of", "the", "in", "for", "a", "an", "to", "with", "on", "at", "by", "as", "is", "are", "be", "we", "you",
    "our", "your", "will", "this", "that", "from", "it", "its", "into", "than", "them", "they", "their", "have", "has",
    "not", "but", "can", "all", "any", "more", "who", "what", "when", "where", "how", "job", "jobs", "role", "roles",
    "position", "positions", "team", "work", "working", "experience", "years", "year", "strong", "good", "skills",
    "ability", "etc", "using", "use", "used", "must", "should", "plus", "und", "der", "die", "das", "mit", "für", "fur",
    "de", "la", "el", "en", "y", "les", "des", "et", "van", "het", "een", "ja", "m/w/d", "w/m/d", "d/m/w", "(m/w/d)",
    "m", "w", "d", "f", "x", "h",
}
GENERIC_ROLE_WORDS = {
    "developer", "developers", "engineer", "engineers", "programmer", "software", "senior", "junior", "lead", "mid",
    "medior", "sr", "jr", "staff", "principal", "specialist", "consultant", "analyst", "architect", "manager",
    "intern", "internship", "graduate", "remote", "hybrid", "onsite", "full", "stack", "fullstack", "full-stack",
    "entwickler", "ingenieur", "desarrollador", "programador", "ingeniero", "ontwikkelaar", "programmeur",
    "kehittäjä", "ohjelmoija", "エンジニア", "開発", "開発者", "developer/engineer", "dev",
}
# local-language / synonym forms of generic role words, used to match titles in other languages
ROLE_SYNONYMS = {
    "developer": ["developer", "engineer", "programmer", "entwickler", "softwareentwickler", "desarrollador", "programador",
                  "ontwikkelaar", "programmeur", "kehittäjä", "ohjelmoija", "ohjelmistokehittäjä", "エンジニア", "開発", "développeur",
                  "sviluppatore", "utvecklare", "programista", "นักพัฒนา", "โปรแกรมเมอร์", "dev"],
    "engineer": ["engineer", "developer", "ingenieur", "ingeniero", "ingénieur", "insinööri", "エンジニア", "วิศวกร", "entwickler", "ingegnere"],
    "programmer": ["programmer", "developer", "programador", "programmeur", "programmierer", "ohjelmoija", "プログラマ", "โปรแกรมเมอร์"],
    "software": ["software", "softwar", "ohjelmisto", "ソフトウェア", "logiciel"],
}


# Words that make a title a software role even when it never says
# "developer" or "engineer" ("Backend (m/w/d)", "SDE-2", "Platform, Java").
TECH_ROLE_WORDS = {
    "backend", "back-end", "frontend", "front-end", "fullstack", "full-stack", "sde", "sde1", "sde2", "sde3",
    "devops", "sre", "platform", "infrastructure", "cloud", "data", "ml", "ai", "qa", "sdet", "test",
    "automation", "mobile", "android", "ios", "web", "api", "microservices", "embedded", "firmware",
    "java", "python", "golang", "node", "nodejs", "react", "angular", "vue", ".net", "dotnet", "c#", "c++",
    "php", "ruby", "rust", "scala", "kotlin", "swift", "typescript", "javascript", "django", "spring",
}

# A title with one of these and no role match is a different profession: the
# search asked for engineering, the board returned its own idea of "related".
OFF_FIELD_WORDS = {
    "sales", "account executive", "business development", "marketing", "recruiter", "recruitment",
    "talent acquisition", "hr ", "human resources", "accountant", "accounting", "finance manager",
    "nurse", "teacher", "tutor", "driver", "chef", "waiter", "barista", "cleaner", "security guard",
    "customer service", "call center", "call centre", "telecaller", "insurance", "real estate",
    "receptionist", "warehouse", "delivery", "mechanic", "electrician", "plumber", "beautician",
}


def tokens(text):
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def content_tokens(text):
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 1]


def slugify(s):
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def today():
    return datetime.now(timezone.utc).date()


def iso(d):
    return d.strftime("%Y-%m-%d")


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(value):
    """Best-effort conversion of many date formats to ISO YYYY-MM-DD (or None)."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}", value.strip())):
            v = float(value)
            if v > 1e12:
                v /= 1000.0
            return iso(datetime.fromtimestamp(v, tz=timezone.utc))
    except Exception:
        pass
    s = str(value).strip()
    s_low = s.lower()
    now = datetime.now(timezone.utc)
    # ISO-like
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # dd/mm/yyyy or dd.mm.yyyy
    m = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if mo > 12 and d <= 12:
            d, mo = mo, d
        try:
            return iso(datetime(y, mo, d))
        except ValueError:
            return None
    # "Sep 10, 2026" / "10 Sep 2026"
    m = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s_low)
    if m and m.group(1) in _MONTHS:
        return iso(datetime(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))))
    m = re.match(r"(\d{1,2})\s+([a-z]{3})[a-z]*\.?\s+(\d{4})", s_low)
    if m and m.group(2) in _MONTHS:
        return iso(datetime(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1))))
    # relative: "2d ago", "Hace 3d", "3 days ago", "vor 2 Tagen", "1w ago", "5h", "Hace 6h", "30+ days ago"
    m = re.search(r"(\d+)\+?\s*(h|hour|hours|d|day|days|w|week|weeks|mo|month|months|tag|tagen|día|dias|días|dag|dagen|päivä|päivää)\b", s_low)
    if m:
        n = int(m.group(1)); u = m.group(2)
        if u.startswith("h"):
            delta = timedelta(hours=n)
        elif u in ("w", "week", "weeks"):
            delta = timedelta(weeks=n)
        elif u in ("mo", "month", "months"):
            delta = timedelta(days=30 * n)
        else:
            delta = timedelta(days=n)
        return iso(now - delta)
    if any(w in s_low for w in ("today", "just now", "hoy", "heute", "vandaag", "tänään", "hours ago", "minutes ago", "new")):
        return iso(now)
    if any(w in s_low for w in ("yesterday", "ayer", "gestern", "gisteren", "eilen")):
        return iso(now - timedelta(days=1))
    return None


def days_old(iso_date):
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").date()
        return (today() - d).days
    except Exception:
        return None


# Minutes / hours in the languages the boards in this bot answer in. A window
# measured in hours is only honest when the source says the time, so this is
# kept apart from parse_date: it returns the exact moment ONLY when there was
# one to read (an epoch, a timestamp, "3 hours ago"), never midnight.
_MIN_WORDS = r"min|mins|minute|minutes|minuten|minuto|minutos|minuutti|minuuttia|นาที|分"
_HOUR_WORDS = r"h|hr|hrs|hour|hours|stunde|stunden|hora|horas|heure|heures|uur|tunti|tuntia|ชั่วโมง|時間"


def parse_when(value):
    """(iso_date, iso_datetime | None) for anything a board calls a posting time.

    The second value is present only when the moment is actually known, so an
    "last 2 hours" search never has to guess what time a date-only posting went
    up. Timestamps are returned in UTC, e.g. "2026-09-18T04:12:00+00:00".
    """
    if value is None or value == "":
        return None, None
    # epoch seconds / milliseconds
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}", value.strip())):
            v = float(value)
            if v > 1e12:
                v /= 1000.0
            dt = datetime.fromtimestamp(v, tz=timezone.utc)
            return iso(dt), dt.isoformat()
    except Exception:
        pass
    s = str(value).strip()
    low = s.lower()
    now = datetime.now(timezone.utc)
    # ISO timestamp with a time in it
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?", s)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5)), int(m.group(6) or 0), tzinfo=timezone.utc)
            off = m.group(8)
            if off and off not in ("Z", "z"):
                sign = 1 if off[0] == "+" else -1
                hh, mm = off[1:].replace(":", "")[:2], off[1:].replace(":", "")[2:4] or "00"
                dt -= timedelta(minutes=sign * (int(hh) * 60 + int(mm)))
            return iso(dt), dt.isoformat()
        except ValueError:
            pass
    # "just now" / "posted moments ago"
    if re.search(r"just (now|posted)|moments? ago|right now|(?<![a-z])now(?![a-z])|juuri|ahora mismo|gerade eben", low):
        return iso(now), now.isoformat()
    # "45 minutes ago" / "vor 45 Minuten" / "hace 45 minutos"
    m = re.search(r"(\d+)\s*(?:" + _MIN_WORDS + r")(?![a-z])", low)
    if m:
        dt = now - timedelta(minutes=int(m.group(1)))
        return iso(dt), dt.isoformat()
    # "3 hours ago" / "vor 3 Stunden" / "hace 3 horas" / "3h"
    m = re.search(r"(\d+)\s*(?:" + _HOUR_WORDS + r")(?![a-z])", low)
    if m:
        dt = now - timedelta(hours=int(m.group(1)))
        return iso(dt), dt.isoformat()
    # anything else is a date at best
    return parse_date(value), None


def hours_old(iso_datetime):
    """Hours since an ISO timestamp, or None when it cannot be read."""
    if not iso_datetime:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_datetime).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def clean_company(s):
    s = normalize_ws(s or "")
    s = re.sub(r"\s*\((m/w/d|w/m/d|d/m/w|f/m/d|m/f/d|h/m|m/f)\)\s*", " ", s, flags=re.I)
    return s.strip(" -|·•")


def clean_title(s):
    s = normalize_ws(s or "")
    s = re.sub(r"\s*\((m/w/d|w/m/d|d/m/w|f/m/d|m/f/d|m/w/x|w/m/x|h/m|m/f|all genders?|gn|x/f/m|m/f/x|f/m/x|m/f/div)\)\s*", " ", s, flags=re.I)
    return normalize_ws(s)
