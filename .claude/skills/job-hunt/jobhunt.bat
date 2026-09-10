@echo off
rem Job Hunt bot launcher. Double-click for interactive mode, or pass arguments:
rem   jobhunt.bat run --role "python developer" --experience 3 --resume "C:\path\cv.pdf" --open
python "%~dp0scripts\job_bot.py" %*
if "%~1"=="" pause
