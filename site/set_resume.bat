@echo off
rem Store a resume for THIS computer: drag a .pdf / .docx / .txt onto this file, or run it and type the path.
rem Every run on this PC (worldwide search, hourly rounds, company-site applies, LinkedIn Premium drafts)
rem uses it from then on. Stored outside the repo in %LOCALAPPDATA%\JobHuntPhone\resume - another PC or
rem another Windows user has its own. Run with no file to see what is stored; "clear" removes it.
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "PY=python"
if exist "..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
if "%~1"=="" (
    "%PY%" tools\resume_store.py show
    echo.
    set /p "F=Path of the resume to store (blank = keep as is): "
    if not "!F!"=="" "%PY%" tools\resume_store.py set "!F!"
) else if /i "%~1"=="clear" (
    "%PY%" tools\resume_store.py clear
) else (
    "%PY%" tools\resume_store.py set "%~1"
)
pause
