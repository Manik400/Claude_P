@echo off
rem Catch-up after sleep / logon / unlock: runs whichever of the three scans
rem (Last 24h, Early, All jobs) the latest slot - 10:00 or 16:00 - is still
rem missing today, then publishes. Does nothing before 10:00 or when the slot's
rem pages are all there. Scheduled by schedule_jobs_agent.ps1 -Mode scan3.
cd /d "%~dp0"
set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" scripts\scan3.py --catchup
