@echo off
rem Daily interview preparation, run by Task Scheduler (NaukriJobAgent-InterviewPrep,
rem see scripts\schedule_jobs_agent.ps1): 100 questions and answers from today's
rem newest scan's Top 10, written as that day's page, then published to the phone.
rem
rem Uses the Claude login in %USERPROFILE%\.claude-interview (login_interview_claude.bat)
rem and costs model tokens - one run a day.
cd /d "%~dp0"
call interview_prep.bat
if errorlevel 1 (
    echo.
    echo   Interview prep failed - see logs\scheduled.log. Nothing to publish.
    exit /b 1
)
call publish_to_phone.bat
