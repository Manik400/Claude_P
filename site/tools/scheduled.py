"""Fill the INPUT_* environment from site/scheduled_searches.json when GitHub started the run on a timer.

The workflows pass `SCHEDULE: ${{ github.event.schedule }}` (the cron line that fired; empty for a run
started from the phone). The entry of `kind` ("jobhunt" or "careers") with that cron wins over every
INPUT_* the workflow set, so a scheduled run is exactly the search written in the file.
"""
import json
import os

FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scheduled_searches.json")
KEYS = ("countries", "experience", "fit", "relocation", "min_salary", "days", "hours", "platforms", "extra", "companies")


def apply(kind, environ=os.environ):
    """-> the entry used (dict), or None for a run that was not started by the timer."""
    cron = (environ.get("SCHEDULE") or "").strip()
    if not cron:
        return None
    with open(FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    entry = next((e for e in cfg.get(kind) or [] if " ".join(e.get("cron", "").split()) == " ".join(cron.split())), None)
    if entry is None:
        raise SystemExit(f"scheduled run ({cron!r}) has no {kind} entry in {FILE}")
    environ["INPUT_ROLE"] = entry.get("roles") or cfg.get("roles") or ""
    for k in KEYS:
        environ["INPUT_" + k.upper()] = str(entry.get(k) or "")
    environ["INPUT_RESUME"] = ""          # the RESUME_TEXT secret
    print(f"scheduled search ({cron}): {entry.get('name') or kind} | countries={entry.get('countries')} "
          f"experience={entry.get('experience')} fit={entry.get('fit')} relocation={entry.get('relocation')} "
          f"min_salary={entry.get('min_salary')} days={entry.get('days')}")
    return entry
