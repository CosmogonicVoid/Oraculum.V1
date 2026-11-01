@echo off
setlocal
cd /d "%~dp0"
call run.cmd repair-local
if errorlevel 1 (
  echo Repair could not finish. Original downloads and portfolios were kept.
  pause
  exit /b 1
)
call research.cmd
exit /b %errorlevel%
