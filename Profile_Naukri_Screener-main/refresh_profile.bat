@echo off
rem The profile nudge, on its own schedule. Bumps your Naukri last-modified
rem timestamp so recruiter searches keep surfacing you near the top.
rem
rem Registered to run every 45 minutes, silently, by:
rem
rem     powershell -ExecutionPolicy Bypass -File scripts\schedule_refresh.ps1
rem
rem Run by hand, a browser window opens while it works. To run it the way the
rem task does (headless browser, no console) start it through the launcher:
rem
rem     wscript //B //Nologo scripts\run_hidden.vbs refresh_profile.bat
rem
rem Every run writes ONE line to logs\refresh.log - success as well as failure -
rem and first trims that log back to the last 24 hours, so it never grows. The
rem line and the trimming are scripts\refresh_log.py; the exit code below is
rem main.py's own (0 refreshed, 1 refresh failed, 2 saved session expired).
rem
rem If it starts failing with "session expired", run: python main.py --login
cd /d "%~dp0"

set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" scripts\refresh_log.py
exit /b %ERRORLEVEL%
