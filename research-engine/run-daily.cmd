@echo off
setlocal
cd /d "%~dp0"
call run.cmd auto-daily %*
exit /b %errorlevel%
