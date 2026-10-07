@echo off
rem Hiring posts from X, Telegram channels, Reddit, Hacker News "Who is hiring", Mastodon and Bluesky
rem (naukri\jobs\social_posts.py), read every 30 minutes and published to the phone's Posts tab
rem next to the LinkedIn ones.
rem
rem     social_posts.bat                       one pass now
rem     social_posts.bat --loop                keep going until this window is closed
rem     social_posts.bat --login-x             sign in to X once (saved session; without it X is skipped)
rem     social_posts.bat --once --source telegram,reddit     only these sources
rem
rem Settings: data\posts\social.yaml (social.example.yaml is the template). Log: logs\social_posts.log.
rem The scheduled task (scripts\schedule_social_posts.ps1, task SocialPostsWatch) runs the loop with pythonw.exe.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if "%~1"=="" (
    "%PY%" -m naukri.jobs.social_posts --once
) else (
    "%PY%" -m naukri.jobs.social_posts %*
)
