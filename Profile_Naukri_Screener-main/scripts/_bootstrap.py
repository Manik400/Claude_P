"""Make `naukri.*` importable from a script run directly, and read its config.

Every script in this folder starts with:

    import _bootstrap                      # noqa: F401

which puts the repository root on sys.path. Previously each script hardcoded an
absolute Windows path to do that, which meant none of them ran on anyone else's
machine, or on the same machine after the folder moved.

The data these scripts type into your profile lives in `profile_edits.yaml`,
which is gitignored - past employers, project descriptions and expected salary
are personal. `profile_edits.example.yaml` is the tracked template.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
EDITS = HERE / "profile_edits.yaml"
EXAMPLE = HERE / "profile_edits.example.yaml"


class EditsError(RuntimeError):
    """profile_edits.yaml is missing, or missing the section a script needs."""


def edits(section: str) -> dict:
    """Return one section of profile_edits.yaml, or explain what to do.

    Scripts here type into a live profile, so a missing section stops the run
    before a browser opens rather than halfway through a dialog.
    """
    import yaml

    if not EDITS.exists():
        raise EditsError(
            f"No {EDITS.name} in {HERE}.\n"
            f"  Copy the template and fill in the '{section}' section:\n"
            f"      cp scripts/{EXAMPLE.name} scripts/{EDITS.name}")
    try:
        data = yaml.safe_load(EDITS.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EditsError(f"{EDITS.name} is not valid YAML: {exc}")

    block = (data or {}).get(section)
    if not block:
        raise EditsError(
            f"{EDITS.name} has no '{section}' section, or it is empty.\n"
            f"  See scripts/{EXAMPLE.name} for what it should contain.")
    return block


def run(main) -> int:
    """Wrap a script's body so a config problem prints a hint, not a traceback."""
    try:
        main()
    except EditsError as exc:
        print(f"\n  {exc}\n")
        return 2
    return 0
