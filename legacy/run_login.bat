@echo off
REM Login to LinkedIn and Naukri (one-time)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python login_setup.py
pause
