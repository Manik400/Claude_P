@echo off
rem One-time setup for the phone site. Double-click and answer the questions.
rem Needs: Python 3.8+, git, and the GitHub CLI (gh) logged in (gh auth login).
cd /d "%~dp0"
set "PY=python"
if exist "..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
"%PY%" tools\setup_phone.py
pause
