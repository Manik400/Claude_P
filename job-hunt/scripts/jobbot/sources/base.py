"""Base classes shared by all source adapters."""
import os
import re

from ..config import COUNTRIES, REMOTE
from ..experience import linkedin_experience_codes
from ..models import Job
from ..textutil import GENERIC_ROLE_WORDS, ROLE_SYNONYMS, content_tokens, days_old, strip_accents


class SearchContext:
    """Everything a source needs to know about one run."""

    def __init__(self, roles, countries, user_years=None, days=30, max_per_source=60, http=None, log=None,
                 exclude_terms=None, must_terms=None, loose=False):
        self.roles = [r.strip() for r in roles if r and r.strip()]
        self.countries = countries
        self.user_years = user_years
        self.days = days
        self.max_per_source = max_per_source
        self.http = http
        self.log = log or (lambda *a, **k: None)
        self.exclude_terms = [t.lower() for t in (exclude_terms or []) if t]
        self.must_terms = [t.lower() for t in (must_terms or []) if t]
        self.loose = loose
        self._role_terms = []
        for role in self.roles:
            toks = content_tokens(strip_accents(role))
            strong = [t for t in toks if t not in GENERIC_ROLE_WORDS]
            weak = [t for t in toks if t in GENERIC_ROLE_WORDS]
            self._role_terms.append((strong, weak))

    # ---- role matching -------------------------------------------------
    @property
    def primary_role(self):
        return self.roles[0] if self.roles else ""

    def keywords(self):
        """Short keyword strings to feed platform search boxes (one per role)."""
        return self.roles or [""]

    def strong_terms(self):
        out = []
        for strong, _ in self._role_terms:
            out.extend(strong)
        return sorted(set(out))

    @staticmethod
    def _has(term, text):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z])", text) is not None

    def relevance(self, title, extra_text=""):
        """0..1 - how well a job matches any requested role."""
        T = strip_accents(title or "").lower()
        X = strip_accents(extra_text or "").lower()
        best = 0.0
        for strong, weak in self._role_terms:
            if strong:
                ht = sum(1 for t in strong if self._has(t, T))
                if ht == len(strong):
                    r = 1.0
                elif ht > 0:
                    r = 0.75
                elif any(self._has(t, X) for t in strong):
                    r = 0.4
                else:
                    r = 0.0
            else:
                expanded = set()
                for w in weak:
                    expanded.update(ROLE_SYNONYMS.get(w, [w]))
                    expanded.add(w)
                hits = sum(1 for t in expanded if t in T)
                r = 1.0 if hits >= min(2, len(weak)) else (0.7 if hits else 0.0)
            best = max(best, r)
        return best

    def excluded(self, title):
        t = (title or "").lower()
        if any(x in t for x in self.exclude_terms):
            return True
        if self.must_terms and not all(m in t for m in self.must_terms):
            return True
        return False

    def fresh(self, iso_date):
        """True when the posting is within the recency window (unknown dates pass)."""
        if not iso_date or not self.days:
            return True
        d = days_old(iso_date)
        return d is None or d <= self.days

    def linkedin_codes(self):
        return linkedin_experience_codes(self.user_years)

    def country_meta(self, code):
        return COUNTRIES.get(code, {})


class Source:
    key = "base"
    name = "Base"
    countries = None        # None = every country in the run; list of ISO2 = only those
    remote_only = False     # True = called once with country=REMOTE
    needs_env = ()          # environment variables required (keyed APIs)
    searchable = True       # False = platform has no keyword search; we filter client-side
    blocked_note = ""       # shown when the site rejects scripts
    homepage = ""

    def enabled(self):
        return all(os.environ.get(v) for v in self.needs_env)

    def applies_to(self, country):
        if self.remote_only:
            return country == REMOTE
        if self.countries is None:
            return country != REMOTE
        return country in self.countries

    def search(self, ctx, country):  # pragma: no cover - abstract
        raise NotImplementedError

    def job(self, **kw):
        kw.setdefault("source", self.key)
        kw.setdefault("source_name", self.name)
        return Job(**kw)

    def __repr__(self):
        return f"<Source {self.key}>"
