@echo off
rem LinkedIn hiring posts: "we are hiring software engineer / SDE / freshers ..." posts from the
rem last 12 hours, read every 30 minutes in a headless browser and published to the phone site's
rem Posts tab (naukri\jobs\linkedin_posts.py).
rem
rem     linkedin_posts.bat                 one pass now (what the scheduled watcher does every 30 min)
rem     linkedin_posts.bat --loop          keep going until this window is closed
rem     linkedin_posts.bat --once --show   one pass with a visible browser
rem
rem The scheduled task (scripts\schedule_linkedin_posts.ps1, task LinkedInPostsWatch) runs the loop
rem with pythonw.exe, so nothing appears on screen; its output is in logs\linkedin_posts.log.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if "%~1"=="" (
    "%PY%" -m naukri.jobs.linkedin_posts --once
) else (
    "%PY%" -m naukri.jobs.linkedin_posts %*
)
