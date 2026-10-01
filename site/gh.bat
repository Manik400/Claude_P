@echo off
rem gh with THIS folder's GitHub login (Claude_P\.gh, gitignored), not the
rem machine-wide one. First time:   site\gh.bat auth login
set "GH_CONFIG_DIR=%~dp0..\.gh"
"C:\Program Files\GitHub CLI\gh.exe" %*
