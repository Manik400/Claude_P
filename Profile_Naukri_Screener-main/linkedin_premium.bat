@echo off
rem LinkedIn Premium runner (naukri\jobs\linkedin_premium.py): reach numbers, who viewed you,
rem Premium's Top Applicant jobs + fresh searches in India and abroad (visa-sponsoring first),
rem Easy Apply to the best, InMail drafts, a like a day, a post draft a day, a daily report.
rem
rem     linkedin_premium.bat                    one pass now (headless)
rem     linkedin_premium.bat --loop             a pass every 4 h until the Premium end date
rem     linkedin_premium.bat --once --show      one pass with a visible browser
rem     linkedin_premium.bat --once --dry-run   read and rank only; apply to nothing, like nothing
rem     linkedin_premium.bat --draft            only today's post draft (no browser)
rem
rem Settings: data\premium\premium.yaml (premium.example.yaml is the template).
rem Report:   data\premium\LATEST.md   Drafts: data\premium\drafts\TODAY.md   Log: logs\linkedin_premium.log
rem Scheduled by scripts\schedule_linkedin_premium.ps1 (task LinkedInPremium, pythonw, nothing on screen).
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if "%~1"=="" (
    "%PY%" -m naukri.jobs.linkedin_premium --once
) else (
    "%PY%" -m naukri.jobs.linkedin_premium %*
)
