@echo off
rem Paste every job-hunt API key once (hidden input, Enter skips one). Each goes
rem into ..\.env for the PC runs and into the GitHub secret of the same name
rem for the phone-started runs, then every key is test-called.
rem Log in to GitHub for this folder first:  ..\site\gh.bat auth login
cd /d "%~dp0.."
set "PY=python"
if exist "Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
"%PY%" job-hunt\scripts\set_key.py --all %*
pause
