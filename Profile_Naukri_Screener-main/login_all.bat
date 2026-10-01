@echo off
rem Sign in to every job platform (and Simplify) once, in the browser that
rem auto-apply uses (%LOCALAPPDATA%\JobHuntPhone\simplify-profile). One tab
rem per platform; you sign in yourself, then come back here and press Enter.
rem Naukri and LinkedIn for the scans themselves have their own logins:
rem     python main.py --login            python main.py --linkedin-login
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" main.py --platform-login %*
pause
