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
rem A browser opens for the ten JD fetches (Naukri blocks headless). After that
rem it is model calls only - roughly ten minutes and a few dollars of tokens.
rem Add --reuse-jds to re-run the analysis without re-opening the job pages.
rem
rem Needs the `claude` CLI on PATH (it reuses your Claude Code login), or
rem ANTHROPIC_API_KEY set plus `pip install anthropic` and --engine anthropic.
cd /d "%~dp0"

set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" main.py --interview-prep %*
