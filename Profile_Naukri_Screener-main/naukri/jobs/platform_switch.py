"""The switch for auto-applying ON job platforms. Off until you turn it on.

Off (the default), the apply pass only submits on company career pages and
the employer's own job pages (career_apply.py): Naukri "Apply on company
site", LinkedIn's plain Apply, and other boards' links out to the employer.
Nothing is sent through a platform's own apply - no Naukri one-click or
questionnaire, no LinkedIn Easy Apply, no Instahyre / Hirist / Wellfound /
SEEK / ... form, even with a saved login there. Those postings are left
untouched, so they are picked up once the switch is on.

The switch is data/jobs/platform_apply.json, flipped from the dashboard's
Settings tab or the phone's Queue -> Rules. `platform_apply:` in jobs.yaml
is used only while that file does not exist.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "data" / "jobs" / "platform_apply.json"
OFF_NOTE = "platform auto-apply is off (turn it on in Settings)"


def stored() -> bool | None:
    """The saved switch, or None when it was never set."""
    try:
        value = json.loads(PATH.read_text(encoding="utf-8")).get("enabled")
        return value if isinstance(value, bool) else None
    except (OSError, ValueError, AttributeError):
        return None


def enabled(config: dict | None = None) -> bool:
    value = stored()
    if value is None:
        value = bool((config or {}).get("platform_apply", False))
    return value


def set_enabled(on: bool) -> bool:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"enabled": bool(on), "at": datetime.now().isoformat(timespec="seconds")},
                               indent=1), encoding="utf-8")
    return bool(on)
