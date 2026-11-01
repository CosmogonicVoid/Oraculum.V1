@echo off
setlocal
cd /d "%~dp0"
if defined LOCALAPPDATA (
  set "ORACULUM_DEMO_DIR=%LOCALAPPDATA%\Oraculum\demo"
) else (
  set "ORACULUM_DEMO_DIR=%~dp0data\demo"
)
call run.cmd demo --data-dir "%ORACULUM_DEMO_DIR%"
if errorlevel 1 goto failed
call run.cmd serve --data-dir "%ORACULUM_DEMO_DIR%" --open-browser
if errorlevel 1 goto failed
exit /b 0
:failed
pause
exit /b 1
