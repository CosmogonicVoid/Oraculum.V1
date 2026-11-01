@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m oraculum.local %*
) else (
  python -m oraculum.local %*
)
exit /b %errorlevel%
