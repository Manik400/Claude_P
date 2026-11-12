"""Per-platform compliance modes from the Career OS directive V2.0.

Reads `career/career_profile.json` -> "platforms" (repo root) and answers, with no
network and no model:

    mode("linkedin")                -> "manual_assist"
    automation_allowed("linkedin")  -> False        (True / False / None, as the file says;
                                                     None = not evaluated yet)
    may_automate("greenhouse")      -> True         (strict: True only when the file says true)
    platform_for_url(url)           -> "linkedin" | "greenhouse" | ... | ""
    entry("lever")                  -> the platform's whole record (a copy)

ADVISORY ONLY. Nothing in the bot calls this module to block, skip or disable anything:
the LinkedIn guest-endpoint source (sources/linkedin.py), the Apify LinkedIn source and
the LinkedIn Easy Apply path (autoapply.py) behave exactly as before. Whether they should
be gated on these answers is the owner's decision - see references/platforms.md,
"Career OS directive V2.0: platform modes".

A platform the file does not name is mode "unknown" with automation_allowed None, and a
missing or unreadable file makes every platform unknown: this module never says
automation is allowed unless the file says so.
"""
import json
import os
import re

UNKNOWN_MODE = "unknown"

# jobbot/ -> scripts/ -> job-hunt/ -> repo root
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_PATH = os.path.join(_REPO_ROOT, "career", "career_profile.json")

# The bot's own source keys and common spellings -> the key used in career_profile.json.
ALIASES = {
    "apify-linkedin": "linkedin",
    "linkedin_web": "linkedin",
    "linkedin.com": "linkedin",
    "linkedin jobs": "linkedin",
    "apify-naukri": "naukri",
    "naukri.com": "naukri",
    "apify-indeed": "indeed",
    "relocateme": "relocate_me",
    "relocate.me": "relocate_me",
    "relocate me": "relocate_me",
    "wellfound_web": "wellfound",
    "angellist": "wellfound",
    "company": "company_career_sites",
    "careers": "company_career_sites",
    "company career sites": "company_career_sites",
    "ashbyhq": "ashby",
}

# host suffix -> platform key, for platform_for_url()
_HOSTS = (
    ("linkedin.com", "linkedin"),
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
    ("naukri.com", "naukri"),
    ("indeed.com", "indeed"),
    ("glassdoor.com", "glassdoor"),
    ("glassdoor.co.in", "glassdoor"),
    ("instahyre.com", "instahyre"),
    ("wellfound.com", "wellfound"),
    ("foundit.in", "foundit"),
    ("cutshort.io", "cutshort"),
    ("relocate.me", "relocate_me"),
    ("wearedevelopers.com", "wearedevelopers"),
)

_cache = {}


def profile_path():
    """CAREER_PROFILE_PATH when set, else <repo>/career/career_profile.json."""
    return os.environ.get("CAREER_PROFILE_PATH") or DEFAULT_PATH


def load_platforms(path=None):
    """{platform key: record} from the profile; {} when the file is missing or unreadable."""
    path = path or profile_path()
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    raw = data.get("platforms") if isinstance(data, dict) else None
    out = {}
    for key, rec in (raw or {}).items():
        if key.startswith("_") or not isinstance(rec, dict):
            continue                      # "_rule" and friends are notes, not platforms
        out[key.lower()] = rec
    _cache[path] = (stamp, out)
    return out


def normalize(platform):
    """'LinkedIn', 'apify-linkedin', 'Relocate.me' -> the key career_profile.json uses."""
    p = re.sub(r"\s+", " ", str(platform or "").strip().lower())
    if p in ALIASES:
        return ALIASES[p]
    return ALIASES.get(p.replace("_", "-"), p.replace("-", "_").replace(" ", "_"))


def entry(platform, path=None):
    """The platform's record (a copy), or {} when the profile does not name it."""
    return dict(load_platforms(path).get(normalize(platform)) or {})


def mode(platform, path=None):
    """'manual_assist' | 'automation_permitted' | 'links_only' | 'evaluate' | ... | 'unknown'."""
    return entry(platform, path).get("mode") or UNKNOWN_MODE


def automation_allowed(platform, path=None):
    """True / False as the profile says; None when it says null or does not name the platform."""
    value = entry(platform, path).get("automation_allowed")
    return value if isinstance(value, bool) else None


def may_automate(platform, path=None):
    """Strict yes/no: True only when the profile explicitly allows automation."""
    return automation_allowed(platform, path) is True


def verified_on(platform, path=None):
    """The date the platform's terms were last read (ISO string), or None when never."""
    return entry(platform, path).get("verified_on") or None


def platform_for_url(url):
    """The profile key of the platform a URL belongs to, or '' when it is none of them."""
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#:]+)", str(url or "").strip().lower())
    host = m.group(1) if m else ""
    for suffix, key in _HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return key
    return ""


def summary(path=None):
    """[(platform, mode, automation_allowed, verified_on)] for every platform, sorted - for docs and logs."""
    return sorted((k, v.get("mode") or UNKNOWN_MODE,
                   v.get("automation_allowed") if isinstance(v.get("automation_allowed"), bool) else None,
                   v.get("verified_on") or None)
                  for k, v in load_platforms(path).items())
