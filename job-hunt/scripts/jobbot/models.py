"""Job record shared by every source."""
import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


@dataclass
class Job:
    source: str                     # registry key, e.g. "linkedin"
    source_name: str                # display name, e.g. "LinkedIn"
    title: str
    company: str
    url: str
    country: str                    # ISO2 code or "REMOTE"
    location: str = ""
    remote: Optional[bool] = None
    posted: Optional[str] = None    # ISO date YYYY-MM-DD when known
    posted_at: Optional[str] = None # ISO timestamp, UTC - ONLY when the board says the time
    posted_raw: str = ""            # what the board actually said ("3 hours ago", an epoch, ...)
    salary: str = ""
    snippet: str = ""               # short plain-text teaser
    description: str = ""           # full plain-text description when available
    skills: List[str] = field(default_factory=list)   # tags supplied by the platform
    employment_type: str = ""
    exp_min: Optional[float] = None
    exp_max: Optional[float] = None
    seniority: str = ""
    fit: str = "unknown"            # fit | stretch | over | no | unknown
    relevance: float = 0.0          # 0..1, how well the title/text matches the requested role
    score: Optional[float] = None   # 0..100 resume match score
    matched_skills: List[str] = field(default_factory=list)
    missing_skills: List[str] = field(default_factory=list)
    also_on: List[str] = field(default_factory=list)  # other platforms carrying the same job
    query: str = ""
    id: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def age_hours(self):
        """Hours since it went up, or None when only the date (or nothing) is known."""
        from .textutil import hours_old
        return hours_old(self.posted_at)

    def finalize(self):
        # A source may hand over the raw value instead of parsing it itself; the
        # exact time is kept apart from the date, so an hours-long window is
        # never satisfied by a date alone.
        if self.posted_raw and not self.posted_at:
            from .textutil import parse_when
            date, at = parse_when(self.posted_raw)
            self.posted = self.posted or date
            self.posted_at = at
        if self.posted_at and not self.posted:
            self.posted = str(self.posted_at)[:10]
        self.title = re.sub(r"\s+", " ", self.title or "").strip()
        self.company = re.sub(r"\s+", " ", self.company or "").strip()
        self.location = re.sub(r"\s+", " ", self.location or "").strip()
        self.snippet = re.sub(r"\s+", " ", self.snippet or "").strip()[:600]
        self.url = (self.url or "").strip()
        self.skills = sorted({s.strip() for s in self.skills if s and s.strip()}, key=str.lower)
        if not self.id:
            self.id = hashlib.sha1(self.dedup_url().encode("utf-8")).hexdigest()[:12]
        return self

    def dedup_url(self):
        u = self.url.split("#")[0]
        u = re.sub(r"[?&](utm_[^&]*|ref[^&]*|trk[^&]*|position=\d+|pageNum=\d+|refId=[^&]*|trackingId=[^&]*|applicationOrigin=[^&]*|page=\d+|sortBy=[^&]*)", "", u)
        return u.rstrip("?&").lower()

    def dedup_key(self):
        return (_norm(self.title), _norm(self.company)[:30], self.country)

    def text_blob(self):
        return " ".join([self.title, self.company, self.snippet, " ".join(self.skills), self.description])

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
