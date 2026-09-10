@echo off
rem One scheduled run of the whole flow. Registered three times a day by:
rem
rem     powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1 -Mode scanprep
rem
rem     1. jobs_scan.bat     search both boards, score, write openings-<date>.html
rem     2. main.py --refresh bump the profile's modified timestamp
rem     3. interview_prep.bat that scan's Top 10 -> 100 Q&A -> its own study page
rem
rem Each step is independent. A failed refresh does not cost you the prep, and a
rem failed prep does not cost you the scan or the refresh - the outputs of the
rem earlier steps are already on disk by then.
rem
rem WHY THE REFRESH IS HERE AND NOT DOING MORE. Naukri's recruiter search ranks
rem on when a profile was last modified, so the whole ranking gain comes from
rem the timestamp. --refresh toggles a full stop on the headline and changes
rem nothing a human reads. It deliberately does NOT rotate skills, move the
rem salary expectation or re-upload the resume: dropping a skill removes you
rem from searches for it until the next run, an expected CTC that moves is one
rem a recruiter quotes back at its lowest value, and every re-upload re-runs
rem Naukri's resume parser over fields you have already had to hand-repair.
rem
rem RUNS DO NOT OVERWRITE EACH OTHER. The prep claims the next free run slot for
rem the day, so the three runs write prep-<date>-r1/-r2/-r3 and three separate
rem pages. The page you were studying at 09:00 is still there at 19:00, and the
rem history picker lists all three by scan time.
rem
rem Runs 2 and 3 are cheaper than run 1: JD text carries across runs of the same
rem day, and questions carry over when the Top 10 has barely moved.
cd /d "%~dp0"

set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

call jobs_scan.bat
if errorlevel 1 (
    echo.
    echo   The scan failed, so there is nothing to prepare from. Stopping here.
    exit /b 1
)

echo.
echo   Scan done. Bumping the profile timestamp...
echo.
"%PY%" main.py --refresh
if errorlevel 1 (
    echo.
    echo   Refresh failed - see logs\naukri.log. Carrying on to the preparation,
    echo   which does not depend on it. If this keeps happening the saved session
    echo   has probably expired: python main.py --login
)

echo.
echo   Building interview preparation from this scan's Top 10...
echo.
call interview_prep.bat %*
