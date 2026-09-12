"""Does a posting offer relocation or visa sponsorship?

assess() reads the title + description and returns a verdict with the sentence that says so, so the
phone page can show the evidence instead of asking you to trust a label.

Labels:  yes      relocation support is offered
         visa     visa sponsorship offered, relocation not mentioned
         maybe    relocation is mentioned without a clear yes/no
         no       relocation or sponsorship explicitly ruled out
         unknown  nothing said
"""
import re

from ..textutil import normalize_ws

_I = re.I

_RELOC_POS = [re.compile(p, _I) for p in (
    r"relocation\s*(?:package|support|assistance|bonus|allowance|budget|help|benefits?|stipend|costs?|services?)",
    r"relocation\s*(?:is\s+|will\s+be\s+|can\s+be\s+)?(?:provided|offered|available|included|covered|possible|supported)",
    r"\b(?:provide|provides|providing|offer|offers|offering|include|includes|cover|covers|support|supports|assist|help)\b[^.;:]{0,50}\brelocat(?:e|ion|ing)",
    r"help(?:ing)?\s+you\s+(?:and\s+your\s+(?:family|loved ones)\s+)?(?:to\s+)?relocate",
    r"(?:visa|immigration)\s*(?:and|&|\+|/)\s*relocation|relocation\s*(?:and|&|\+|/)\s*(?:visa|immigration)",
    r"open\s+to\s+(?:candidates\s+)?(?:willing\s+to\s+)?relocat",
    r"umzugs(?:hilfe|pauschale|unterst\w*|kosten)|relocation-(?:paket|unterst\w*)",
    r"verhuis(?:vergoeding|kosten|ondersteuning)",
    r"(?:ayuda|apoyo|paquete)\s+(?:de|a|para)\s+(?:la\s+)?reubicaci",
)]
_RELOC_NEG = [re.compile(p, _I) for p in (
    r"\bno\s+relocation\b",
    r"relocation\s*(?:is\s+|will\s+)?not\s+(?:be\s+)?(?:provided|offered|available|supported|possible|covered)",
    r"relocation\s*:\s*(?:no|none|not\s+available)\b",
    r"(?:only|exclusively)\s+(?:consider|accept|open\s+to)\s+(?:local\s+)?candidates\s+(?:who\s+are\s+)?(?:already\s+)?(?:based|located|residing|living)",
)]
_VISA_POS = [re.compile(p, _I) for p in (
    r"visa\s*(?:sponsorship|support|assistance|processing)",
    r"\b(?:we|will|can|able\s+to|happy\s+to)\s+(?:sponsor|provide\s+sponsorship)",
    r"sponsor(?:ship)?\s+(?:of\s+|for\s+)?(?:your\s+|the\s+|a\s+)?(?:work\s+)?(?:visa|permit|blue\s+card)",
    r"work\s+permit\s+(?:support|assistance|sponsorship)",
    r"blue\s+card\s+(?:support|sponsorship)",
)]
_VISA_NEG = [re.compile(p, _I) for p in (
    r"(?:no|without(?:\s+the\s+need\s+for)?(?:\s+requiring)?)\s+(?:visa\s+|work\s+permit\s+)?sponsorship",
    r"sponsorship\s+(?:is\s+|will\s+)?not\s+(?:be\s+)?(?:available|provided|offered|possible)",
    r"\b(?:must|should|need\s+to)\s+(?:already\s+)?(?:have|hold|possess|be\s+eligible\s+to\s+obtain)\s+(?:the\s+|a\s+|valid\s+|full\s+|existing\s+)?"
    r"(?:right|authori[sz]ation|eligibility|permit)\s+to\s+work",
    r"\b(?:not|unable\s+to|cannot|can't|can\s+not|won't|will\s+not|do\s+not|don't|does\s+not)\s+(?:be\s+able\s+to\s+)?"
    r"(?:offer|provide|support|sponsor)\b[^.;]{0,40}(?:visa|sponsorship|work\s+permit)",
    r"\b(?:cannot|can't|unable\s+to|not\s+able\s+to)\s+sponsor",
)]
_NEGATED = re.compile(r"\b(?:no|not|unable|cannot|can't|won't|without|neither|nor|don't|doesn't|isn't)\b[^.;]*$", _I)
_NEGATED_AFTER = re.compile(r"^[^.;]{0,20}?\b(?:not|unavailable)\b", _I)  # "relocation support is not available"
_WEAK = re.compile(r"relocat|umzug|reubicaci|verhuiz|d[ée]m[ée]nagement", _I)


def _sentence(text, start, end):
    s = text.rfind(". ", 0, start)
    s = max(s + 2 if s >= 0 else 0, start - 120)
    if s > 0 and not text[s - 1].isspace():  # do not start mid-word
        sp = text.find(" ", s, start)
        s = sp + 1 if sp >= 0 else s
    e = text.find(". ", end)
    e = min(len(text) if e < 0 else e + 1, end + 160)
    if e < len(text) and text[e - 1] != ".":
        sp = text.rfind(" ", end, e)
        e = sp if sp > end else e
    out = text[s:e].strip()
    return ("…" if s > 0 else "") + out + ("…" if e < len(text) else "")


def _scan(pos, neg, text):
    """-> (verdict, match). A positive phrase with a negation right before or after it counts as negative."""
    first_pos = first_neg = None
    for rx in neg:
        m = rx.search(text)
        if m and (first_neg is None or m.start() < first_neg.start()):
            first_neg = m
    for rx in pos:
        for m in rx.finditer(text):
            if _NEGATED.search(text[max(0, m.start() - 45):m.start()]) or _NEGATED_AFTER.search(text[m.end():m.end() + 30]):
                if first_neg is None:
                    first_neg = m
                continue
            if first_pos is None or m.start() < first_pos.start():
                first_pos = m
            break
    if first_pos and first_neg:
        return "mixed", first_pos
    if first_pos:
        return "yes", first_pos
    if first_neg:
        return "no", first_neg
    return "unknown", None


def assess(title, text):
    """-> dict(label, relocation, visa, evidence)"""
    t = normalize_ws((title or "") + ". " + (text or ""))
    reloc, rm = _scan(_RELOC_POS, _RELOC_NEG, t)
    visa, vm = _scan(_VISA_POS, _VISA_NEG, t)
    if reloc in ("yes", "mixed"):
        label, m = ("yes" if reloc == "yes" else "maybe"), rm
    elif visa == "yes":
        label, m = "visa", vm
    elif reloc == "no" or visa == "no":
        label, m = "no", rm or vm
    else:
        w = _WEAK.search(t)
        label, m = ("maybe", w) if w else ("unknown", None)
    evidence = _sentence(t, m.start(), m.end())[:360] if m else ""
    return {"label": label, "relocation": reloc, "visa": visa, "evidence": evidence}
