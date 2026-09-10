@echo off
rem Daily profile nudge. Bumps your Naukri last-modified timestamp so you keep
rem surfacing near the top of recruiter searches. Schedule this once a day via
rem Task Scheduler.
rem
rem IT NEEDS A DESKTOP TO DRAW INTO. main.py forces refresh(headless=False)
rem because Akamai serves "Access Denied" to headless Chromium, so a visible
rem browser window opens while it works. Register the task as "Run only when
rem the user is logged on" - under "whether user is logged on or not" there is
rem no session for the browser to appear in and the job fails every single day.
rem
rem NOTE: this file is currently registered in no scheduled task. The refresh
rem that actually runs is step 2 of jobs_scan_and_prep.bat, three times a day.
rem See the README's note on how often the nudge is worth running.
rem
rem If it starts failing, your saved session has expired - run:
rem     python main.py --login
cd /d "%~dp0"
python main.py --refresh
