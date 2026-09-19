@echo off
rem AI interview preparation for today's Top 10 jobs.
rem
rem Reads the scan that jobs_scan.bat already wrote, takes the ten
rem highest-scoring jobs, fetches each one's FULL description (the scan only
rem stores a teaser), and builds:
rem
rem     data\interview\interview-prep-<date>.html   the study page
rem     data\interview\prep-<date>.json             the analysis and 100 Q&A
rem     data\interview\bank.json                    every question ever asked
rem
rem What it produces: a collective read of what those ten employers want, a
rem skill matrix scored against your resume, an honest gap list, and 100 unique
rem interview questions with answers - 30 basic, 40 intermediate, 30 advanced.
rem
rem RUN THE SCAN FIRST. This analyses today's results file; without one it
rem stops and tells you so rather than analysing a stale day.
rem
rem A browser opens for the ten JD fetches (headless, so nothing on screen,
rem when run through scripts\run_hidden.vbs or with NAUKRI_BACKGROUND=1). After
rem that it is model calls only - roughly ten minutes and a few dollars of tokens.
rem Add --reuse-jds to re-run the analysis without re-opening the job pages.
rem
rem MODEL: Claude Opus 5 at effort "high", always - --model anything else is
rem refused and a reply from another model is discarded.
rem
rem LOGIN: the `claude` CLI is run with its own login folder
rem (%USERPROFILE%\.claude-interview), NOT the login Claude Code uses. Sign in
rem there once with the organisation (Max plan) account:
rem     login_interview_claude.bat
rem Alternatively set ANTHROPIC_API_KEY, `pip install anthropic`, and pass
rem --engine anthropic (same model and effort).
cd /d "%~dp0"

set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" main.py --interview-prep %*
