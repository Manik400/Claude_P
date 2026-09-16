@echo off
rem Run the one auto-apply queue (phone: Jobs -> Queue all; Queue tab).
rem Reads the phone's requests on the gh-pages branch, folds them into
rem data/apply/queue.enc, applies on Naukri + LinkedIn with the screener's
rem own walkers - a few per board per run, spaced out - and publishes every
rem item's status, the progress and any screening questions back for the phone.
rem
rem Scheduled every 30 minutes and after logon by site\schedule_phone_apply.ps1
rem (hidden). By hand:
rem     phone_apply.bat                 up to NAUKRI_APPLY_LIMIT applies per board (default 5)
rem     phone_apply.bat --dry-run       show what it would do
cd /d "%~dp0"
set "PY=python"
if exist "..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
"%PY%" tools\phone_apply.py %*
