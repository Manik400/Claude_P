@echo off
rem Push the newest Naukri openings page(s) and interview-prep page(s) to the
rem phone site (encrypted, on the gh-pages branch). Safe to run any time:
rem pages already published are skipped.
rem
rem Setup once: ..\site\setup_phone.bat
cd /d "%~dp0"
set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -c "import cryptography" 2>nul || "%PY%" -m pip install -q cryptography
"%PY%" "..\site\tools\phone_publish.py" naukri %*
