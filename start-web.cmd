@echo off
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
 echo Install Node.js 24 or newer, then reopen this file.
 pause
 exit /b 1
)
if not exist node_modules (
 echo Install dependencies first: npx --yes pnpm@11.25.0 install --frozen-lockfile
 pause
 exit /b 1
)
call npm run dev
pause
