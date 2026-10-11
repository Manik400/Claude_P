@echo off
rem Search again with the settings of your last run, add what the top-paying
rem companies' own career pages list, then apply to everything the run found:
rem LinkedIn Easy Apply, Naukri, and company-site forms (no login / CAPTCHA).
rem
rem   1. job_bot.py run --like-last             the worldwide search, scored, reported
rem   2. careers_bot.py run                     career pages of assets\companies_top_india.txt
rem                                             (big tech, fintech unicorns, HFT / quant):
rem                                             India, 0-2 years, last 14 days, 10 min at most
rem   3. job_bot.py merge                       those postings into the run (re-scored)
rem   4. job_bot.py apply --yes                 the apply pass; APPLY_MAX_MINUTES bounds it,
rem                                             NAUKRI_APPLY_LIMIT (if set) caps each board
rem
rem Uses the Naukri screener next door for the logins, the Easy Apply walker,
rem the company-form filler, your answers (its dashboard.bat) and the shared
rem applications log, so run it with THAT project's virtualenv (Playwright).
rem
rem Scheduled by scripts\schedule_jobhunt.ps1. By hand:
rem     jobhunt_apply.bat                 (cap from NAUKRI_APPLY_LIMIT, else the daily caps)
rem     set NAUKRI_APPLY_LIMIT=5 && jobhunt_apply.bat
rem
rem A failed careers step never stops the round: the apply pass still runs on
rem what the worldwide search found.
rem
rem Questions it cannot answer land in ..\Profile_Naukri_Screener-main\data\jobs\questions.yaml;
rem answer them in that project's dashboard.bat and the next run re-attempts those jobs.
cd /d "%~dp0"
set "PY=python"
if exist "..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"

rem Strict about time: a posting whose time cannot be shown to be inside the window
rem (12 h, from your last run) is dropped, after its own page was read for a date
rem (up to 150 pages). The report then lists only what is new - jobs already applied
rem to, removed on the phone, or listed by an earlier report are left out
rem (scripts\jobbot\memory.py); the apply pass still carries the earlier runs' unapplied ones.
rem --max-minutes 40: no new source/country search starts after 40 min, so a crawling
rem network cannot stretch the search phase into the apply window.
rem Any title, 0-2 years (2026-10-11): --experience 0-2 drops postings that ask for more
rem (the fit filter) and searches LinkedIn at entry/associate level; --loose keeps every
rem software title the boards return, whatever it is called (other fields are still dropped);
rem --exclude drops senior / lead / manager / intern titles on the title alone.
"%PY%" scripts\job_bot.py run --like-last --experience 0-2 --loose ^
    --exclude "senior,sr.,sr ,principal,staff ,architect,manager,director,head of,intern" ^
    --strict-undated --verify-dates 150 --max-minutes 40 %*
if errorlevel 1 exit /b %ERRORLEVEL%

set "CAREERS_OUT=%TEMP%\jobhunt_careers.json"
if exist "%CAREERS_OUT%" del /q "%CAREERS_OUT%"
rem Career pages are read whole, so the roles here only decide which titles count: list them all.
"%PY%" scripts\careers_bot.py run --role "software engineer,software developer,sde,swe,backend engineer,backend developer,full stack developer,full stack engineer,frontend developer,frontend engineer,web developer,application developer,java developer,python developer,platform engineer,devops engineer,site reliability engineer,qa engineer,sdet,data engineer,mobile developer,android developer,ios developer,junior developer,junior software engineer,graduate software engineer,associate software engineer,programmer,member of technical staff,software development engineer,new grad software engineer,early career software engineer" ^
    --experience 0-2 --countries IN --relocation any --hours 48 --max-minutes 10 ^
    --companies-file assets\companies_top_india.txt --out "%CAREERS_OUT%"
if exist "%CAREERS_OUT%" "%PY%" scripts\job_bot.py merge --file "%CAREERS_OUT%" --quiet

"%PY%" scripts\job_bot.py apply --yes %*
exit /b %ERRORLEVEL%
