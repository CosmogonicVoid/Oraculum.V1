@echo off
setlocal
cd /d "%~dp0"
call run.cmd serve --open-browser
if errorlevel 1 pause
