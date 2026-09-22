@echo off
rem Daily job SCAN. Searches Naukri and LinkedIn, scores everything against
rem your profile, and writes:
rem
rem     data\jobs\openings-<date>.html   the tracker page you work through
rem     data\jobs\job-matches-<date>.xlsx
rem     data\jobs\results-<date>.json
rem
rem This is a DAILY DIGEST, not a standing shortlist. Two filters keep it to
rem what actually changed since yesterday:
rem
rem     --posted-days 1   only listings the board says went up in the last 24h
rem     --new-only        only jobs that have not appeared on an earlier day's
rem                       page, tracked in data\jobs\seen.json
rem
rem So a short list is the normal result - most mornings there are genuinely
rem only a handful of new 24-hour-old postings. Drop both flags for the full
rem standing list:
rem
rem     python main.py --jobs-export --top 60
rem
rem THIS RUN APPLIES. After the scan it clicks Apply on every Naukri posting
rem it listed (one-click ones, and questionnaire ones it can answer from your
rem profile, jobs.yaml and data\jobs\answer_bank.yaml) and Easy Apply on every
rem LinkedIn posting that offers it. "Apply on company site" postings are left
rem for you. A screening question it cannot answer is saved to
rem data\jobs\questions.yaml - answer those at the end of the day with
rem     python main.py --answer-questions
rem and the next run applies to the jobs that were waiting on them.
rem
rem To scan without applying, drop the two flags at the bottom:
rem     python main.py --jobs-export --top 60 --posted-days 1 --new-only
rem
rem To prepare for what it finds, run interview_prep.bat afterwards - it takes
rem this scan's Top 10 and builds a study page of 100 interview questions.
rem jobs_scan_and_prep.bat does both in one go.
rem
rem If it starts failing, a saved session has expired - run:
rem     python main.py --login            (Naukri)
rem     python main.py --linkedin-login   (LinkedIn)
cd /d "%~dp0"

rem Task Scheduler does not inherit your shell's PATH, so prefer the repo venv
rem over whatever "python" happens to resolve to under the scheduler account.
set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

rem No --worldwide and no --locations: the scan covers the WHOLE COUNTRY with no
rem city filter. --worldwide widened the LinkedIn half past India, which for a
rem 0-2 year candidate on an India profile is mostly postings that cannot hire
rem you; the worldwide hunt is job-hunt's job. Naming cities is the other
rem extreme - it narrows the query AND throws away every listing outside them.
"%PY%" main.py --jobs-export --top 60 --posted-days 1 --new-only --apply-found --yes
