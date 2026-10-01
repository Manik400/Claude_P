@echo off
rem Job Hunt bot launcher. Double-click for interactive mode, or pass arguments:
rem   jobhunt.bat run --role "python developer" --experience 3 --resume "C:\path\cv.pdf" --open
set "PY=python"
if exist "%~dp0..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=%~dp0..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
"%PY%" "%~dp0scripts\job_bot.py" %*
if "%~1"=="" pause
