@echo off
rem Sign in to the NEW LinkedIn account, then switch every LinkedIn service back on.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m naukri.jobs.linkedin_resume %*
pause
