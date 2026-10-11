"""The job-hunt project's shared modules (jobbot.*), for this project's pages and scorer.

    from .jobhunt_bridge import jobbot
    mnc = jobbot("mnc")                 # module, or None when job-hunt is not next door
    salary_lookup = jobbot("salary_lookup")

job-hunt/scripts holds the company list (mnc.txt + mnc.py), the pay reader
(salary.py) and the pay lookup (salary_lookup.py). Both projects read the same
files, so a company is an "MNC" and a posting "~₹18 LPA" on every page alike.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

log = logging.getLogger("naukri.jobs.jobhunt_bridge")
ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT.parent / "job-hunt" / "scripts"
_missing: set[str] = set()


def jobbot(name: str):
    """jobbot.<name>, or None (logged once per name) when it cannot be imported."""
    if name in _missing:
        return None
    if str(SCRIPTS) not in sys.path and SCRIPTS.exists():
        sys.path.insert(0, str(SCRIPTS))
    try:
        return importlib.import_module(f"jobbot.{name}")
    except Exception as exc:  # noqa: BLE001 - job-hunt absent or its dependency missing: the page simply lacks the field
        _missing.add(name)
        log.debug("jobbot.%s not available: %s", name, exc)
        return None


def pay_of(title: str, company: str, stated_label: str = "", stated_text: str = "", country: str = "IN",
           allow_web: bool = True) -> dict:
    """{lpa, kind, source, mnc, mnc_tier, mnc_name} for a posting: the stated pay (a Naukri
    label like "6-9 Lacs PA", or a figure in the text) first, else the looked-up estimate."""
    out: dict = {"lpa": None, "kind": "", "source": "", "mnc": False, "mnc_tier": "", "mnc_name": ""}
    mnc_mod = jobbot("mnc")
    if mnc_mod is not None:
        m = mnc_mod.match(company or "")
        if m:
            out.update(mnc=True, mnc_tier=m["tier"], mnc_name=m["name"])
    sal = jobbot("salary")
    if sal is not None:
        s = None
        if stated_label and not re.search(r"not disclosed|undisclosed|competitive|negotiable", stated_label, re.I):
            s = sal.parse(stated_label)
        if s is None and stated_text:
            s = sal.find_in_text(stated_text)
        if s is not None and s.top_inr:
            out.update(lpa=round(s.top_inr / 100_000, 1), kind="stated", source="the posting")
            return out
    look = jobbot("salary_lookup")
    if look is not None and company:
        try:
            est = look.estimate(title or "", company, country, allow_web=allow_web)
        except Exception as exc:  # noqa: BLE001
            log.debug("pay lookup failed for %s @ %s: %s", title, company, exc)
            est = None
        if est:
            out.update(lpa=est.get("lpa"), kind=est.get("kind") or "est", source=est.get("source") or "", lo=est.get("lo"), hi=est.get("hi"))
    return out


import re  # noqa: E402  (used by pay_of)
