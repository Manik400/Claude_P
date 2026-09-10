# Job Hunt bot + Claude skill

Searches ~20 job platforms by role and experience, groups jobs by country, adds an Apply button per job,
and scores each job against your resume (resume stays on your computer).

## Setup (once)
1. Install Python 3.8+ from python.org (tick "Add Python to PATH").
2. Double-click `install.bat` (or run `python -m pip install --user -r requirements.txt`).

## Use without Claude
Double-click `jobhunt.bat` and answer the questions, or run:

    python scripts/job_bot.py run --role "flutter developer" --experience 3 --resume "C:\path\cv.pdf" --open

Reports are saved in `Documents\JobHunt\<date>_<role>\report.html`.
Other commands: `python scripts/job_bot.py -h`.

## Use with Claude
Put this folder in `%USERPROFILE%\.claude\skills\job-hunt` (or install `job-hunt.skill`),
then ask Claude e.g. "find python developer jobs in Germany and Japan, 3 years experience, here is my CV".

## Optional API keys (more coverage)
ADZUNA_APP_ID + ADZUNA_APP_KEY, JOOBLE_API_KEY, RAPIDAPI_KEY (JSearch), FIRECRAWL_API_KEY.
