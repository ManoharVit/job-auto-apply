@echo off
REM Full daily run — what the scheduler calls
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py >> logs\cron.log 2>&1
