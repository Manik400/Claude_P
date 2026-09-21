"""The company list (job-hunt/assets/companies.txt).

A row is   Name | ats | board | note   and may carry a career-page link in the note column
or in a fifth one:

    Agoda   | greenhouse | agoda    | Bangkok hub
    OpenAI  | ashby      | openai   | https://jobs.ashbyhq.com/openai | San Francisco
    Rakuten | link       | -        | https://rakuten.careers/        | read the link, no API
    Zepto   | auto       | -        | Bengaluru                       | find the board on the first run

A link that names a job board (greenhouse / lever / ashby / smartrecruiters / workable /
recruitee / workday) is authoritative: its ats and board win over the columns, because a
link is something you checked and a slug is something someone guessed. A link to a plain
career page is kept as the company's careers URL and read once, to find the board behind it.

`ats` may be `auto` (or `-`, or a system this bot cannot read): the row is not dropped, it
is resolved on the first run by jobbot.careers.resolve and remembered in assets/boards_cache.json.
"""
import os
from dataclasses import dataclass, field

ATS_TYPES = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "workday")
AUTO = ("auto", "-", "?", "unknown", "")
LINK = ("link", "url", "official", "site")
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                            "assets", "companies.txt")


@dataclass
class Company:
    name: str
    ats: str
    board: str
    note: str = ""
    url: str = ""           # careers link from the row, when it gave one
    resolved: str = ""      # how the board was found, once resolve.py has had a say
    line: int = 0           # its line in companies.txt, for `resolve --write`
    aliases: tuple = field(default_factory=tuple)

    @property
    def careers(self):
        """The link a human should click for this company."""
        return self.board_url or self.url

    @property
    def board_url(self):
        b = self.board
        if not b or self.ats not in ATS_TYPES:
            return ""
        if self.ats == "greenhouse":
            return f"https://job-boards.greenhouse.io/{b}"
        if self.ats == "lever":
            return f"https://jobs.lever.co/{b}"
        if self.ats == "ashby":
            return f"https://jobs.ashbyhq.com/{b}"
        if self.ats == "smartrecruiters":
            return f"https://jobs.smartrecruiters.com/{b}"
        if self.ats == "workable":
            return f"https://apply.workable.com/{b}"
        if self.ats == "recruitee":
            return f"https://{b}.recruitee.com"
        if self.ats == "workday":
            host, _, site = b.split("/", 2)
            return f"https://{host}/{site}"
        return ""

    @property
    def readable(self):
        """Can this row be fetched right now, or does it need resolving first?"""
        return self.ats in ATS_TYPES and bool(self.board) and not (self.ats == "workday" and self.board.count("/") < 2)


def _is_url(s):
    return bool(s) and s.lower().startswith(("http://", "https://", "www."))


def load(path=None, log=None):
    """Read the company list. Rows are never dropped for a bad board - they are marked `auto`.

    A single stale slug must not cost a company its whole row (that is what the 404s were),
    so anything unreadable becomes a row to resolve, and only a nameless row is skipped.
    `skipped` on the returned list says what was dropped, `auto` how many need resolving.
    """
    path = path or DEFAULT_PATH
    out, by_name, skipped = [], {}, []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            name = parts[0] if parts else ""
            if not name:
                skipped.append((n, line[:40], "no company name"))
                continue
            ats = (parts[1].lower() if len(parts) > 1 else "").strip()
            board = (parts[2] if len(parts) > 2 else "").strip()
            rest = [p for p in parts[3:] if p]
            url = next((p for p in [board] + rest if _is_url(p)), "")
            if url and not url.lower().startswith("http"):
                url = "https://" + url
            note = " ".join(p for p in rest if p != url)

            # A link that names a board is the truth; the ats/board columns are a guess.
            from .resolve import from_url  # local import: resolve imports Company from here
            link_ats, link_board = from_url(url)
            if link_ats:
                ats, board = link_ats, link_board
            else:
                if _is_url(board) or board in ("-", "?"):
                    board = ""
                if ats not in ATS_TYPES:          # 'official', 'oracle', 'link', '-', blank...
                    ats = "auto"
                if ats == "workday" and board.count("/") < 2:
                    board = ""                    # keep the ats as a hint, drop the unusable board

            c = Company(name, ats, board, note, url, line=n)
            first = by_name.get(name.lower())
            if first:
                _merge(first, c)          # the same company listed twice: keep the row that knows more
                continue
            by_name[name.lower()] = c
            out.append(c)
    # A `link` row with its URL was already resolved as "no API": only a bare one still needs a board.
    linked = sum(1 for c in out if not c.readable and c.url)
    auto = sum(1 for c in out if not c.readable) - linked
    if log and (skipped or auto or linked):
        bits = []
        if auto:
            bits.append(f"{auto} row(s) need a board (resolved on first use)")
        if linked:
            bits.append(f"{linked} link-only row(s)")
        if skipped:
            bits.append(f"{len(skipped)} row(s) skipped")
        log("companies.txt: %d companies; %s" % (len(out), ", ".join(bits)))
    out = _CompanyList(out)
    out.skipped = skipped
    return out


def _merge(first, dup):
    """Fold a duplicate row into the one already kept: a real board and a link beat blanks."""
    if not first.readable and dup.readable:
        first.ats, first.board = dup.ats, dup.board
    if not first.url and dup.url:
        first.url = dup.url
    if dup.note and dup.note not in first.note:
        first.note = (first.note + "; " + dup.note).strip("; ") if first.note else dup.note


class _CompanyList(list):
    """A plain list of Company, plus a `skipped` note from load()."""
    skipped = ()


def select(companies, names_text):
    """Keep companies whose name or board contains any of the comma-separated terms (empty = all)."""
    terms = [t.strip().lower() for t in (names_text or "").split(",") if t.strip()]
    if not terms:
        return companies
    return [c for c in companies if any(t in c.name.lower() or t in (c.board or "").lower() for t in terms)]
