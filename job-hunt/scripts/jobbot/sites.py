"""The site list (job-hunt/assets/sites.txt) - which platforms a run may search.

The same idea as the company list next to it: one line per site, `key | on/off
| note`, so turning a platform off is an edit rather than a code change. A run
that names platforms itself (`--sources`, or the phone's chips) overrides the
file; "off" here is the default for everything that does not.

A missing or unreadable file means every platform is on, which is what an
untouched checkout should do.
"""
import os

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "sites.txt")


def load(path=None):
    """{key: {"on": bool, "note": str}} for every line in the file."""
    out = {}
    try:
        with open(path or DEFAULT_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        key = parts[0].lower()
        state = (parts[1] if len(parts) > 1 else "on").lower()
        if not key:
            continue
        out[key] = {"on": state not in ("off", "no", "0", "false"),
                    "note": parts[2] if len(parts) > 2 else ""}
    return out


def disabled(path=None):
    """Keys switched off in the file."""
    return [k for k, v in load(path).items() if not v["on"]]


def note(key, path=None):
    return (load(path).get(str(key).lower()) or {}).get("note", "")


def unknown_keys(valid_keys, path=None):
    """Keys in the file that no source answers to - a typo, or a renamed source."""
    return sorted(set(load(path)) - set(valid_keys))
