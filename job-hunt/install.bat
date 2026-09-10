@echo off
rem Installs the Python packages the Job Hunt bot needs (Python 3.8+ must already be installed).
python -m pip install --user -r "%~dp0requirements.txt"
echo.
echo Done. Double-click jobhunt.bat to start the bot.
pause
