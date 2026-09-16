@echo off
rem Search again with the settings of your last run, then apply to the
rem LinkedIn postings it found (Easy Apply) - a few per run, spaced out.
rem
rem Uses the Naukri screener next door for the LinkedIn login, the Easy Apply
rem walker, your answers (its dashboard.bat) and the shared applications log,
rem so run it with THAT project's virtualenv, which has Playwright installed.
rem
rem Scheduled by scripts\schedule_jobhunt.ps1. By hand:
rem     jobhunt_apply.bat                 (cap from NAUKRI_APPLY_LIMIT, else the daily cap)
rem     set NAUKRI_APPLY_LIMIT=5 && jobhunt_apply.bat
rem
rem Questions it cannot answer land in ..\Profile_Naukri_Screener-main\data\jobs\questions.yaml;
rem answer them in that project's dashboard.bat and the next run re-attempts those jobs.
cd /d "%~dp0"
set "PY=python"
if exist "..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
"%PY%" scripts\job_bot.py run --like-last --apply-found --yes %*
