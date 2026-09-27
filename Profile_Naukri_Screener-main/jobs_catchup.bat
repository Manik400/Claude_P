@echo off
rem Runs whichever of the day's three scans (Last 24h, Early, All jobs) has
rem not run today, between 10:00 and 23:00 - same as jobs_scan_3way.bat. No
rem longer scheduled on its own: the NaukriJobAgent-Scan3 task does this.
cd /d "%~dp0"
set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" scripts\scan3.py
