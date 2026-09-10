@echo off
rem Daily scan (same as jobs_scan.bat, sends nothing) and then push the new
rem openings page to the phone site. Point Task Scheduler at this file to get
rem the Naukri digest on your phone without touching the PC:
rem
rem   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1 -Mode scanpublish
cd /d "%~dp0"
call jobs_scan.bat
call publish_to_phone.bat
