@echo off
setlocal
cd /d "%~dp0"
set "OLLAMA_HOST=127.0.0.1:11434"
set "OLLAMA_NO_CLOUD=1"
where ollama >nul 2>nul
if errorlevel 1 goto missing
echo Oraculum local AI setup. The model requires several GB of free disk space.
echo Start the Ollama app before continuing. No paid API or account is needed.
ollama pull qwen3.5:2b
if errorlevel 1 goto failed
call run.cmd ai-configure --model qwen3.5:2b
if errorlevel 1 goto failed
call run.cmd ai-evaluate
if errorlevel 1 goto evaluation_failed
echo.
echo Development checks passed. Model selection and event tone still need review.
echo Run: .\run.cmd ai-refresh
echo Then open start.cmd and select Briefs.
echo Future research.cmd runs include a bounded AI batch while Ollama is running.
pause
exit /b 0
:evaluation_failed
call run.cmd ai-disable
echo The model checks did not all pass. Generation has been disabled.
echo Evidence notebooks and ordinary research remain available.
echo Inspect docs\MILESTONE_7.md and the evaluation output before retrying.
pause
exit /b 1
:missing
echo Install Ollama from https://ollama.com/download/windows and start its app.
echo Reopen the terminal after installation, then run ai-setup.cmd again.
pause
exit /b 1
:failed
echo Setup did not complete. Inspect the error above and run .\run.cmd ai-doctor.
pause
exit /b 1
