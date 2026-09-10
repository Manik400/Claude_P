@echo off
rem Daily job SCAN. Searches Naukri and LinkedIn, scores everything against
rem your profile, and writes:
rem
rem     data\jobs\openings-<date>.html   the tracker page you work through
rem     data\jobs\job-matches-<date>.xlsx
rem     data\jobs\results-<date>.json
rem
rem This is a DAILY DIGEST, not a standing shortlist. Two filters keep it to
rem what actually changed since yesterday:
rem
rem     --posted-days 1   only listings the board says went up in the last 24h
rem     --new-only        only jobs that have not appeared on an earlier day's
rem                       page, tracked in data\jobs\seen.json
rem
rem So a short list is the normal result - most mornings there are genuinely
rem only a handful of new 24-hour-old postings. Drop both flags for the full
rem standing list:
rem
rem     python main.py --jobs-export --worldwide --top 60
rem
rem This run SENDS NOTHING. It finds jobs and reports them; you apply.
rem For the version that also applies, see jobs_agent.bat.
rem
rem To prepare for what it finds, run interview_prep.bat afterwards - it takes
rem this scan's Top 10 and builds a study page of 100 interview questions.
rem jobs_scan_and_prep.bat does both in one go.
rem
rem If it starts failing, a saved session has expired - run:
rem     python main.py --login            (Naukri)
rem     python main.py --linkedin-login   (LinkedIn)
cd /d "%~dp0"

rem Task Scheduler does not inherit your shell's PATH, so prefer the repo venv
rem over whatever "python" happens to resolve to under the scheduler account.
set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" main.py --jobs-export --worldwide --top 60 --posted-days 1 --new-only
