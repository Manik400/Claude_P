@echo off
rem The day's three scans, then publish the pages to the phone site. Each runs
rem ONCE a day, between 10:00 and 23:00 - a run that finds them done exits
rem (scripts\scan3.py). "jobs_scan_3way.bat --force" runs all three now.
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
rem
rem Checked every 30 min 10:00-23:00 and on wake/logon/unlock/reconnect by:
rem     powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1 -Mode scan3
cd /d "%~dp0"

set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" scripts\scan3.py %*
