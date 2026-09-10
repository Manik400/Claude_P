"""jobbot - multi-platform job search, resume match scoring and HTML report generation.

Entry point: scripts/job_bot.py (CLI). Package layout:
  config.py      countries table, defaults
  models.py      Job dataclass
  http.py        polite HTTP session (rate limit, retries)
  textutil.py    html->text, tokenizing, date parsing
  experience.py  "X years" parsing, seniority, fit classification
  resume.py      PDF/DOCX/TXT text extraction
  scoring.py     resume <-> job match score
  search.py      orchestrator (runs sources concurrently, dedups, filters)
  details.py     fetch full job descriptions for top jobs
  fallback.py    blocked platforms: direct search links + web-search query plan + merge
  render.py      HTML report
  sources/       one adapter per platform
"""
__version__ = "1.0.0"
