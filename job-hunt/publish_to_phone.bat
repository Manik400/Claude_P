@echo off
rem Push a job-hunt report made on this PC to the phone site.
rem   publish_to_phone.bat "C:\Users\you\Documents\JobHunt\2026-09-11_python-developer\report.html"
rem Drag the report.html onto this file, or run it with no argument to publish the newest run.
cd /d "%~dp0"
set "PY=python"
if exist "..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=..\Profile_Naukri_Screener-main\.venv\Scripts\python.exe"
"%PY%" -c "import cryptography" 2>nul || "%PY%" -m pip install -q --disable-pip-version-check cryptography 2>nul || "%PY%" -m pip install -q --disable-pip-version-check --user cryptography
if "%~1"=="" (
  for /f "delims=" %%d in ('dir /b /ad /o-d "%USERPROFILE%\Documents\JobHunt"') do (
    "%PY%" "..\site\tools\phone_publish.py" jobhunt "%USERPROFILE%\Documents\JobHunt\%%d\report.html"
    goto :done
  )
) else (
  "%PY%" "..\site\tools\phone_publish.py" jobhunt "%~1"
)
:done
pause
