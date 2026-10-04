@echo off
REM Check how many jobs have been applied to
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py --stats
pause
