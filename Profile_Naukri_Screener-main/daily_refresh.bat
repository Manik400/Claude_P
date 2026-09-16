@echo off
rem Daily profile nudge. Bumps your Naukri last-modified timestamp so you keep
rem surfacing near the top of recruiter searches. Schedule this once a day via
rem Task Scheduler.
rem
rem Run by hand, a browser window opens while it works. To run it silently
rem (headless browser, no console) start it through the hidden launcher:
rem     wscript //B //Nologo scripts\run_hidden.vbs daily_refresh.bat
rem Register the task as "Run only when the user is logged on": the off-screen
rem fallback browser needs a desktop session to exist.
rem
rem NOTE: this file is currently registered in no scheduled task. The refresh
rem that actually runs is step 2 of jobs_scan_and_prep.bat, three times a day.
rem See the README's note on how often the nudge is worth running.
rem
rem If it starts failing, your saved session has expired - run:
rem     python main.py --login
cd /d "%~dp0"
python main.py --refresh
