"""Role packs: the one place a career field is described.

Everything else in this toolkit is field-agnostic. The parts that are not -
which keywords to search, which words mean "this is my field", which skills to
count across ten job descriptions - are pulled out into `roles/*.yaml` so a
support engineer or a SOC analyst can use the same code as an SDET by changing
one line of jobs.yaml:

    role: cybersecurity

A pack is data, not code. Adding a fifth role means writing a fifth YAML file
and nothing else. See docs/ROLES.md for the format and for how to write one.

Packs inherit from `roles/_common.yaml`, which holds the skills that show up in
every technical job advert - Git, Docker, Linux, SQL, cloud, Agile, JIRA. A
role pack lists only what is specific to its field, so the four shipped packs
stay short enough to read in one sitting.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

import yaml

log = logging.getLogger("naukri.roles")

ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = ROOT / "roles"
JOBS_YAML = ROOT / "jobs.yaml"

COMMON = "_common"
DEFAULT_ROLE = "qa-automation"

# Cache keyed by role name. The lexicon is compiled into regexes downstream, so
# re-reading four YAML files per question would be measurable on a 100-question
# run for no gain - a pack never changes mid-process.
_CACHE: dict[str, dict] = {}


class RoleError(RuntimeError):
    """The named role pack is missing or unusable."""


def available() -> list[str]:
    """Role names that can be put in jobs.yaml, alphabetically."""
    if not ROLES_DIR.is_dir():
        return []
    return sorted(p.stem for p in ROLES_DIR.glob("*.yaml")
                  if not p.stem.startswith("_"))


def active_name(jobs_yaml: Path = JOBS_YAML) -> str:
    """The role named in jobs.yaml, or the default.

    Read straight out of the YAML rather than through jobs.config, because the
    interview modules need the role before a profile has been extracted and
    jobs.config refuses to load without one.
    """
    if not jobs_yaml.exists():
        return DEFAULT_ROLE
    try:
        data = yaml.safe_load(jobs_yaml.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        log.warning("%s unreadable (%s); using the %s role pack",
                    jobs_yaml.name, exc, DEFAULT_ROLE)
        return DEFAULT_ROLE
    name = str((data or {}).get("role") or "").strip()
    return name or DEFAULT_ROLE


def _read(name: str) -> dict:
    path = ROLES_DIR / f"{name}.yaml"
    if not path.exists():
        known = ", ".join(available()) or "none found"
        raise RoleError(
            f"No role pack '{name}'. Set `role:` in jobs.yaml to one of: {known}.\n"
            f"  To add your own, copy an existing file in roles/ - see docs/ROLES.md.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RoleError(f"{path} is not valid YAML: {exc}")
    if not isinstance(data, dict):
        raise RoleError(f"{path} must be a YAML mapping.")
    return data


def _merge_lexicon(base: dict, extra: dict) -> "OrderedDict[str, tuple[str, tuple[str, ...]]]":
    """Fold a pack's lexicon over the common one, keeping insertion order.

    A role may redefine a common skill - cybersecurity wants "Python" to match
    scripting aliases the QA pack has no use for - so a name present in both
    takes the role's definition, in the common pack's original position.
    """
    merged: "OrderedDict[str, tuple[str, tuple[str, ...]]]" = OrderedDict()
    for source in (base, extra):
        for canonical, spec in (source or {}).items():
            if isinstance(spec, dict):
                category = str(spec.get("category") or "Other")
                aliases = tuple(str(a).lower() for a in (spec.get("aliases") or []))
            else:
                # Shorthand: `Kafka: [Data, kafka, apache kafka]`
                items = [str(x) for x in (spec or [])]
                category, aliases = (items[0] if items else "Other"), tuple(
                    a.lower() for a in items[1:])
            if not aliases:
                # A skill with no aliases can never match; dropping it beats
                # compiling a pattern for the canonical name and pretending.
                log.warning("role pack skill %r has no aliases - ignored", canonical)
                continue
            merged[canonical] = (category, aliases)
    return merged


def load(name: str | None = None) -> dict:
    """The fully resolved pack: common inherited, role layered on top."""
    name = name or active_name()
    if name in _CACHE:
        return _CACHE[name]

    role = _read(name)
    common = _read(COMMON) if role.get("extends", COMMON) == COMMON and name != COMMON else {}

    def joined(key: str) -> list:
        out, seen = [], set()
        for item in list(common.get(key) or []) + list(role.get(key) or []):
            marker = str(item).lower()
            if marker not in seen:
                seen.add(marker)
                out.append(item)
        return out

    pack = {
        "name": name,
        "label": role.get("label") or name.replace("-", " ").title(),
        "primary_role": role.get("primary_role") or role.get("label") or name,
        "seed_keywords": list(role.get("seed_keywords") or []),
        "searches": list(role.get("searches") or []),
        "must_have_any": joined("must_have_any"),
        "exclude_title_keywords": joined("exclude_title_keywords"),
        "synonyms": {**(common.get("synonyms") or {}), **(role.get("synonyms") or {})},
        "tight_terms": {str(t).lower() for t in joined("tight_terms")},
        "lexicon": _merge_lexicon(common.get("lexicon") or {}, role.get("lexicon") or {}),
        "interview_focus": role.get("interview_focus") or "",
    }
    if not pack["lexicon"]:
        raise RoleError(f"Role pack '{name}' resolved to an empty skill lexicon.")

    _CACHE[name] = pack
    return pack


def summarise(pack: dict) -> str:
    """One paragraph about a pack, for --roles."""
    categories: "OrderedDict[str, int]" = OrderedDict()
    for _canonical, (category, _aliases) in pack["lexicon"].items():
        categories[category] = categories.get(category, 0) + 1
    spread = ", ".join(f"{c} {n}" for c, n in
                       sorted(categories.items(), key=lambda kv: -kv[1])[:6])
    return (f"  {pack['name']:<16} {pack['label']}\n"
            f"  {'':<16} {len(pack['lexicon'])} skills ({spread})\n"
            f"  {'':<16} seeds: {', '.join(pack['seed_keywords'][:5]) or '-'}\n")
