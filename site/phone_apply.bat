@echo off
rem Carry out the auto-apply requests made from the phone (Reports -> a
rem worldwide report -> Auto-apply). Reads the queue on the gh-pages branch,
rem applies to the LinkedIn postings with the Naukri screener's applier - a few
rem per poll, spaced out - and publishes each posting's status and any
rem screening questions back for the phone to show.
rem
rem Scheduled every 30 minutes by site\schedule_phone_apply.ps1 (hidden). By hand:
rem     phone_apply.bat                 up to NAUKRI_APPLY_LIMIT applies (default 5)
rem     phone_apply.bat --dry-run       show what it would do
cd /d "%~dp0"
set "PY=python"
if exist "..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
"%PY%" tools\phone_apply.py %*
