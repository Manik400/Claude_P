@echo off
rem Daily job agent. Searches Naukri, scores every result against your profile,
rem applies to the strong one-click matches and queues the rest for you.
rem
rem Runs LIVE - it submits real applications. Drop the --yes to make a run
rem report what it would do without sending anything.
rem
rem Scheduled three times a day by scripts\schedule_jobs_agent.ps1. The daily
rem application cap in jobs.yaml is enforced across all three runs, not per run,
rem so a re-run after a failure cannot start the day's quota over.
rem
rem If it starts failing, your saved session has expired - run:
rem     python main.py --login
cd /d "%~dp0"

rem Task Scheduler does not inherit your shell's PATH, so prefer the repo venv
rem over whatever "python" happens to resolve to under the scheduler account.
set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" main.py --jobs --yes
