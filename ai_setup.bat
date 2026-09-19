@echo off
rem Install the free local model both tools can use (no key, no cloud):
rem
rem     ranking      an embedding model reads the whole posting against your
rem                  resume / profile (job-hunt scoring, Naukri score)
rem     fit lines    "why it fits / gap" for the top jobs on every report
rem     answers      screening questions no rule covers, from your facts only
rem     relocation   a second opinion on maybe / unknown postings (careers bot)
rem
rem Runs on the CPU. Downloads once, ~1.4 GB, into %USERPROFILE%\.cache\jobbot-ai.
rem
rem     ai_setup.bat          Qwen 3.5 2B (default, ~1.3 GB, fast enough anywhere)
rem     ai_setup.bat /big     Qwen 3.5 4B (~2.5 GB, better answers, slower)
rem
rem Nothing else changes: the scans and the phone queue pick the model up on
rem their next run. Remove it with:  pip uninstall llama-cpp-python fastembed
rem To switch it off without uninstalling, put LOCAL_AI=0 in %~dp0.env.
cd /d "%~dp0"

set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if exist "Profile_Naukri_Screener-main\.venv\Scripts\python.exe" set "PY=Profile_Naukri_Screener-main\.venv\Scripts\python.exe"

set "MODEL=unsloth/Qwen3.5-2B-GGUF:Qwen3.5-2B-Q4_K_M.gguf"
if /i "%~1"=="/big" set "MODEL=unsloth/Qwen3.5-4B-GGUF:Qwen3.5-4B-Q4_K_M.gguf"

echo.
echo   Installing the local model packages (prebuilt CPU wheels, nothing to compile)...
echo.
"%PY%" -m pip install -r job-hunt\requirements-ai.txt --only-binary llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 (
    echo.
    echo   pip failed. If it says no matching wheel for llama-cpp-python, your Python is
    echo   newer than the prebuilt wheels cover - see job-hunt\requirements-ai.txt.
    pause
    exit /b 1
)

rem Record the model choice for every run (both tools read <repo>\.env).
findstr /b /c:"LOCAL_AI_MODEL=" .env >nul 2>&1 || (echo LOCAL_AI_MODEL=%MODEL%>> .env)
set "LOCAL_AI_MODEL=%MODEL%"

echo.
echo   Downloading %MODEL% and the embedding model (once)...
echo.
"%PY%" job-hunt\scripts\jobbot\localai.py --download
if errorlevel 1 (
    echo   Download failed - check the connection and run this again.
    pause
    exit /b 1
)

echo.
echo   Smoke test (one embedding, one answer)...
echo.
"%PY%" job-hunt\scripts\jobbot\localai.py --smoke
if errorlevel 1 (
    echo.
    echo   The model did not run. If the message names an unknown architecture, the installed
    echo   llama-cpp-python predates Qwen 3.5: set LOCAL_AI_MODEL=unsloth/Qwen3-1.7B-GGUF:Qwen3-1.7B-Q4_K_M.gguf
    echo   in %~dp0.env and run this again.
    pause
    exit /b 1
)
echo.
echo   Done. The next scan / search / queue run uses the local model.
pause
