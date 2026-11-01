@echo off
setlocal
cd /d "%~dp0"
call run.cmd auto-daily
if errorlevel 1 (
  echo.
  echo Daily workflow did not complete. Cached downloads and saved records were kept.
  echo Rerun to resume. If the paper phase failed, the new research report is still available.
  pause
  exit /b 1
)
call run.cmd serve --open-browser
if errorlevel 1 (
  echo If port 8765 is occupied, stop the previous Oraculum viewer terminal and run start.cmd.
  pause
  exit /b 1
)
