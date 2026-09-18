"""Read `.env` files, so keys and tokens live in one place outside the code.

Secrets only: API keys for the keyed sources (Adzuna, Jooble, JSearch,
Firecrawl, Apify) and the contact finders. Everything you answer - roles,
countries, screening answers - belongs in the data files instead
(`Profile_Naukri_Screener-main/data/jobs/answer_bank.yaml`, each run's
`run.json`), because those carry options, dates and per-job context that a
KEY=value line cannot.

Files are read in this order and NEVER override a variable already set in the
environment, so a value exported for one run still wins:

    <repo>/.env
    <repo>/job-hunt/.env
    %LOCALAPPDATA%/JobHuntPhone/.env      (or ~/.config/jobhunt/.env)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
JOBHUNT = os.path.dirname(SCRIPTS)
REPO = os.path.dirname(JOBHUNT)


def _config_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "JobHuntPhone" if os.environ.get("LOCALAPPDATA") else "jobhunt")


def candidates():
    return [os.path.join(REPO, ".env"), os.path.join(JOBHUNT, ".env"), os.path.join(_config_dir(), ".env")]


def parse(text):
    """KEY=value lines -> dict. `export KEY=value`, #comments and quotes are handled."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load_env(paths=None, log=None):
    """Load every .env that exists. Returns the names loaded (not the values)."""
    loaded = []
    for path in paths or candidates():
        try:
            with open(path, encoding="utf-8") as f:
                values = parse(f.read())
        except (OSError, UnicodeDecodeError):
            continue
        for key, value in values.items():
            if key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
        if log and values:
            log(f"env: {len(values)} setting(s) from {path}")
    return loaded
