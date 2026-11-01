@echo off
setlocal
cd /d "%~dp0"
call run.cmd schedule-install
if errorlevel 1 (
  echo Task Scheduler operation failed. Review the message above.
  pause
  exit /b 1
)
echo Task Scheduler operation completed.
pause
