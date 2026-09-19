@echo off
rem Sign in the Claude account that the INTERVIEW PREPARATION uses.
rem
rem The preparation (interview_prep.bat) runs the `claude` CLI with its own
rem login folder, %USERPROFILE%\.claude-interview, so the account you sign in
rem here is independent of the one Claude Code uses for coding. Sign in with
rem the ORGANISATION account (the Max plan): pick that organisation when the
rem browser asks. The model is fixed to Claude Opus 5 at high effort.
rem
rem Run once; run again if the preparation says nobody is signed in.
cd /d "%~dp0"
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-interview"
if not "%INTERVIEW_CLAUDE_CONFIG_DIR%"=="" set "CLAUDE_CONFIG_DIR=%INTERVIEW_CLAUDE_CONFIG_DIR%"
set "CLAUDECODE="
if not exist "%CLAUDE_CONFIG_DIR%" mkdir "%CLAUDE_CONFIG_DIR%"
echo.
echo   Signing in to Claude for the interview preparation.
echo   Login folder: %CLAUDE_CONFIG_DIR%
echo   Choose the ORGANISATION (Max plan) account in the browser.
echo.
claude auth login
echo.
claude auth status
echo.
echo   Done. interview_prep.bat now uses this account (Claude Opus 5, effort high).
pause
