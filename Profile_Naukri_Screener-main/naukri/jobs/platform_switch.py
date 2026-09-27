"""Per-platform switches for auto-applying THROUGH a job platform.

A platform's switch covers the platform's OWN apply: Naukri's one-click and
questionnaire, LinkedIn Easy Apply, Instahyre / Hirist / Wellfound / SEEK /
XING / Indeed forms. It never covers the employer's site: a Naukri "Apply on
company site" posting, a LinkedIn plain-Apply posting or a board's link out to
the employer is still opened and its career form filled and submitted
(career_apply.py) whatever the platform's switch says - only the platform's
own apply button is left alone while that platform is off.

Default: every platform on except Naukri and LinkedIn (their own applies are
the ones that draw account restrictions when a bot bursts through them).

The switches live in data/jobs/platform_apply.json:

    {"platforms": {"naukri": false, "linkedin": false, "instahyre": true, ...}}

flipped from the dashboard's Settings tab or the phone's Queue -> Rules. The
older one-switch file ({"enabled": true|false}) and `platform_apply:` in
jobs.yaml are still read: `true` means every platform on, `false` means the
default above (Naukri and LinkedIn off, the rest on).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "data" / "jobs" / "platform_apply.json"
OFF_NOTE = "platform auto-apply is off (turn it on in Settings)"

# (key, label, host substrings). "other" is every platform not listed.
PLATFORMS: list[tuple[str, str, tuple[str, ...]]] = [
    ("naukri", "Naukri", ("naukri.com",)),
    ("linkedin", "LinkedIn Easy Apply", ("linkedin.com",)),
    ("instahyre", "Instahyre", ("instahyre.com",)),
    ("hirist", "Hirist", ("hirist.",)),
    ("cutshort", "Cutshort", ("cutshort.io",)),
    ("foundit", "foundit", ("foundit.in", "monster.")),
    ("wellfound", "Wellfound", ("wellfound.com", "angel.co")),
    ("indeed", "Indeed", ("indeed.",)),
    ("glassdoor", "Glassdoor", ("glassdoor.",)),
    ("seek", "SEEK / JobsDB / Jobstreet", ("seek.com", "jobsdb.com", "jobstreet.com")),
    ("xing", "XING", ("xing.com",)),
    ("stepstone", "StepStone", ("stepstone.",)),
    ("relocateme", "Relocate.me", ("relocate.me",)),
    ("other", "Other boards (iimjobs, Shine, TimesJobs, apna, InfoJobs, ...)", ()),
]
KEYS = [k for k, _l, _h in PLATFORMS]
LABELS = {k: label for k, label, _h in PLATFORMS}
DEFAULT_OFF = ("naukri", "linkedin")


def defaults() -> dict[str, bool]:
    return {k: k not in DEFAULT_OFF for k in KEYS}


def _read() -> dict | None:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def stored() -> dict[str, bool] | None:
    """The saved switches (every key filled in), or None when never set."""
    data = _read()
    if data is None:
        return None
    if isinstance(data.get("platforms"), dict):
        out = defaults()
        for k, v in data["platforms"].items():
            if k in out and isinstance(v, bool):
                out[k] = v
        return out
    if isinstance(data.get("enabled"), bool):       # the old one-switch file
        return {k: True for k in KEYS} if data["enabled"] else defaults()
    return None


def platforms(config: dict | None = None) -> dict[str, bool]:
    """Every platform -> on/off, from the saved file, else jobs.yaml `platform_apply`, else the defaults."""
    value = stored()
    if value is not None:
        return value
    yaml_value = (config or {}).get("platform_apply", None)
    if yaml_value is True:
        return {k: True for k in KEYS}
    return defaults()


def platform_of(url_or_key: str) -> str:
    """The platform key for a URL (or a key passed through); "other" for an unlisted board."""
    text = (url_or_key or "").lower()
    if text in KEYS:
        return text
    host = re.sub(r"^https?://(www\.)?", "", text).split("/")[0]
    for key, _label, hosts in PLATFORMS:
        if any(h in host for h in hosts):
            return key
    return "other"


def allowed(url_or_key: str, config: dict | None = None) -> bool:
    """May the platform's own apply be used for this URL / platform key?"""
    return bool(platforms(config).get(platform_of(url_or_key), True))


def enabled(config: dict | None = None, platform: str | None = None) -> bool:
    """One platform's switch; with no platform, whether ANY platform is on."""
    if platform:
        return allowed(platform, config)
    return any(platforms(config).values())


def off_note(url_or_key: str) -> str:
    return f"{LABELS.get(platform_of(url_or_key), 'platform')} auto-apply is off (turn it on in Settings)"


def set_enabled(value) -> dict[str, bool]:
    """Save the switches. `value` is a bool (every platform), or {key: bool} merged into the saved ones.
    Returns the switches as saved."""
    current = platforms()
    if isinstance(value, dict):
        for k, v in value.items():
            if k in current and isinstance(v, bool):
                current[k] = v
    else:
        current = {k: bool(value) for k in KEYS}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"platforms": current, "at": datetime.now().isoformat(timespec="seconds")},
                               indent=1), encoding="utf-8")
    return current


def summary(config: dict | None = None) -> str:
    p = platforms(config)
    off = [LABELS[k].split(" /")[0] for k in KEYS if not p[k]]
    if not off:
        return "auto-apply on every platform"
    if all(not v for v in p.values()):
        return "platform auto-apply off everywhere (company sites only)"
    return "platform auto-apply off for " + ", ".join(off) + " - on for the rest"
