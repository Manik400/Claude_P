"""The company list (job-hunt/assets/companies.txt)."""
import os
from dataclasses import dataclass

ATS_TYPES = ("greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workday")
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                            "assets", "companies.txt")


@dataclass
class Company:
    name: str
    ats: str
    board: str
    note: str = ""

    @property
    def careers(self):
        b = self.board
        if self.ats == "greenhouse":
            return f"https://job-boards.greenhouse.io/{b}"
        if self.ats == "lever":
            return f"https://jobs.lever.co/{b}"
        if self.ats == "ashby":
            return f"https://jobs.ashbyhq.com/{b}"
        if self.ats == "smartrecruiters":
            return f"https://jobs.smartrecruiters.com/{b}"
        if self.ats == "recruitee":
            return f"https://{b}.recruitee.com"
        if self.ats == "workday":
            host, _, site = b.split("/", 2)
            return f"https://{host}/{site}"
        return ""


def load(path=None, log=None):
    """Read the company list, skipping rows this bot cannot read.

    A single bad row must never abort a whole search, so rows with an
    unsupported ats or a malformed board are counted and reported, not
    raised on. `skipped` on the returned list says what was dropped.
    """
    path = path or DEFAULT_PATH
    out, seen, skipped = [], set(), []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3 or not parts[0] or not parts[2]:
                skipped.append((n, parts[0] if parts else line[:40], "expected 'Name | ats | board | note'"))
                continue
            name, ats, board = parts[0], parts[1].lower(), parts[2]
            if ats not in ATS_TYPES:
                skipped.append((n, name, f"unsupported ats '{ats}'"))
                continue
            if ats == "workday" and board.count("/") < 2:
                skipped.append((n, name, "workday board is not <host>/<tenant>/<site>"))
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append(Company(name, ats, board, parts[3] if len(parts) > 3 else ""))
    if skipped and log:
        by_reason = {}
        for _n, _name, reason in skipped:
            by_reason.setdefault(reason.split("'")[0].strip(), 0)
            by_reason[reason.split("'")[0].strip()] += 1
        log("companies.txt: %d of %d rows skipped (%s)" % (
            len(skipped), len(skipped) + len(out),
            ", ".join(f"{v} {k}" for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1]))))
    out = _CompanyList(out)
    out.skipped = skipped
    return out


class _CompanyList(list):
    """A plain list of Company, plus a `skipped` note from load()."""
    skipped = ()


def select(companies, names_text):
    """Keep companies whose name or board contains any of the comma-separated terms (empty = all)."""
    terms = [t.strip().lower() for t in (names_text or "").split(",") if t.strip()]
    if not terms:
        return companies
    return [c for c in companies if any(t in c.name.lower() or t in c.board.lower() for t in terms)]
