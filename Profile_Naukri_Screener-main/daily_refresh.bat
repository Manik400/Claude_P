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
rem NOTE: this file is registered in no scheduled task, and you probably want
rem refresh_profile.bat instead - same nudge, but it is the one the every-45-
rem minute task runs (scripts\schedule_refresh.ps1) and it logs one line per
rem run to logs\refresh.log. This file stays for a once-a-day task of your own.
rem The scan runs also refresh as step 2 of jobs_scan_and_prep.bat.
rem
rem If it starts failing, your saved session has expired - run:
rem     python main.py --login
cd /d "%~dp0"
python main.py --refresh
