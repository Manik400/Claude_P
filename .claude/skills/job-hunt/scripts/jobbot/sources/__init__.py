"""Source registry."""
from .adzuna import Adzuna
from .arbeitnow import Arbeitnow
from .daijob import Daijob
from .duunitori import Duunitori
from .firecrawl import FirecrawlSearch
from .infojobs import InfoJobs
from .instahyre import Instahyre
from .japandev import JapanDev
from .jobicy import Jobicy
from .jobthai import JobThai
from .jooble import Jooble
from .jsearch import JSearch
from .landingjobs import LandingJobs
from .linkedin import LinkedIn
from .relocateme import RelocateMe
from .remoteok import RemoteOK
from .remotive import Remotive
from .seek import Seek
from .tecnoempleo import Tecnoempleo
from .themuse import TheMuse
from .tokyodev import TokyoDev
from .wantedly import Wantedly
from .wellfound import Wellfound
from .workingnomads import WorkingNomads
from .xing import Xing

# Order matters only for display. Keyed sources are skipped automatically when their env vars are absent.
ALL_SOURCES = [
    LinkedIn(), Seek(), Xing(), Arbeitnow(), Duunitori(), Tecnoempleo(), InfoJobs(), Wellfound(),
    TokyoDev(), JapanDev(), Daijob(), Wantedly(), JobThai(), TheMuse(), LandingJobs(), RelocateMe(),
    Instahyre(), Remotive(), RemoteOK(), Jobicy(), WorkingNomads(),
    Adzuna(), Jooble(), JSearch(), FirecrawlSearch(),
]

BY_KEY = {s.key: s for s in ALL_SOURCES}


def select_sources(include=None, exclude=None, remote=True):
    chosen = []
    for s in ALL_SOURCES:
        if include and s.key not in include:
            continue
        if exclude and s.key in exclude:
            continue
        if not remote and s.remote_only:
            continue
        if not s.enabled():
            continue
        chosen.append(s)
    return chosen
