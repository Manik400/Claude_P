@echo off
rem Three scans in a row, then publish all three pages to the phone site:
rem
rem     1. Last 24h   --posted-days 1 --new-only   postings from the last day
rem                                                 not listed on an earlier day
rem     2. Early      --early                      posted in the last few hours,
rem                                                 or LinkedIn "early applicant"
rem     3. All jobs   (no date filter)             the full standing list
rem
rem Each run writes its own openings-<date>-r<N>.html, titled "Last 24h",
rem "Early" or "All jobs", and applies like jobs_scan.bat does (per-run cap
rem from NAUKRI_APPLY_LIMIT, daily caps from jobs.yaml shared by every run).
rem
rem They run one after another, never at the same time: every run drives the
rem same saved browser profile, and two at once crash each other. The work
rem is done by scripts\scan3.py, which also holds a lock against overlap.
rem jobs_catchup.bat runs only the scans the current slot is missing.
rem
rem Scheduled at 10:00 and 16:00 by:
rem     powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1 -Mode scan3
cd /d "%~dp0"

set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" scripts\scan3.py %*
