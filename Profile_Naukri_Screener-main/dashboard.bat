@echo off
rem The dashboard: one local page to edit your answers, answer the questions
rem the agent could not, and follow every application and the replies to it.
rem Opens http://127.0.0.1:8765 in your browser. Close this window to stop it.
cd /d "%~dp0"
set "PY=python"
if exist "..\venv\Scripts\python.exe" set "PY=..\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" main.py --dashboard %*
