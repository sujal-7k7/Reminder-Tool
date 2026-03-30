@echo off

REM Move to the exact directory where this batch file lives
cd /d "%~dp0"

REM Run the python script using the virtual environment, pipe all output to the log file
.venv\Scripts\python.exe run_scheduler.py >> logs\scheduler_console.log 2>&1