"""Helpers for remote job boards: decide which of the user's countries a remote job is open to."""
from ..config import REMOTE, countries_in_text, regions_in_text, COUNTRY_WORDS, REGION_WORDS

WORLD_WORDS = ("worldwide", "anywhere", "global", "world wide", "any location", "all countries", "international", "everywhere")


def assign_country(location_text, ctx):
    """Return (country_code, eligible_codes) or (None, []) when the job is closed to every target country."""
    cands = [c for c in ctx.countries if c != REMOTE]
    text = (location_text or "").strip()
    if not text:
        return REMOTE, cands
    low = text.lower()
    hits = countries_in_text(text, cands)
    regions = regions_in_text(text, cands)
    worldwide = any(w in low for w in WORLD_WORDS)
    if worldwide:
        return REMOTE, cands
    if len(hits) == 1 and not regions:
        return hits[0], hits
    eligible = list(dict.fromkeys(hits + regions))
    if eligible:
        return REMOTE, eligible
    # the text names *other* countries/regions -> closed to the user's targets
    other_country = any(w in low for words in COUNTRY_WORDS.values() for w in words if len(w) > 3)
    other_region = any(r in low for r in REGION_WORDS)
    if other_country or other_region or any(w in low for w in ("usa", "us only", "united states", "canada", "latam", "uk only")):
        return None, []
    # unrecognised free text ("CET +/- 3h", "EU timezone") -> keep as remote, eligibility unknown
    return REMOTE, []
