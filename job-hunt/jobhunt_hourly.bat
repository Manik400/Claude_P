@echo off
rem One round of the job hunt, then the next round is set for -Gap minutes
rem (default 30) after THIS round finished.
rem
rem     worldwide search like last time -> LinkedIn Easy Apply + company sites
rem
rem The Naukri scan is NOT part of a round: the day's three Naukri scans run
rem once a day from the NaukriJobAgent-Scan3 task (scripts\scan3.py).
rem
rem Company sites: skipped when they want a login or show a CAPTCHA, otherwise
rem filled and submitted (..\Profile_Naukri_Screener-main\naukri\jobs\career_apply.py).
rem
rem Scheduled (hidden) by scripts\schedule_jobhunt.ps1 as the task JobHuntApply.
rem Before the round starts the next one is also set as a backstop, so a round
rem that is killed or crashes still gets a successor.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1 -Rearm -Backstop
call jobhunt_apply.bat %*
set "RC=%ERRORLEVEL%"
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1 -Rearm
exit /b %RC%
