@echo off
REM ============================================================
REM setup_windows.bat — One-click setup for Windows
REM Right-click -> "Run as Administrator" (first time only)
REM ============================================================

echo.
echo ========================================
echo   Job Auto-Apply Bot - Windows Setup
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! 
    echo         Download from: https://www.python.org/downloads/
    echo         IMPORTANT: Check "Add Python to PATH" during install!
    pause
    exit /b 1
)
echo [OK] Python found

REM Create virtual environment
echo [..] Creating virtual environment...
python -m venv .venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create venv
    pause
    exit /b 1
)
echo [OK] Virtual environment created

REM Activate and install
echo [..] Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)
echo [OK] Dependencies installed

REM Install Playwright Chromium
echo [..] Installing Chromium browser (this may take a minute)...
playwright install chromium
if %errorlevel% neq 0 (
    echo [ERROR] Playwright browser install failed
    pause
    exit /b 1
)
echo [OK] Chromium installed

REM Create directories
if not exist "resume" mkdir resume
if not exist "logs" mkdir logs
if not exist "sessions" mkdir sessions

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
echo Next steps:
echo   1. Put your resume PDF in the "resume" folder
echo   2. Edit config.yaml with your LinkedIn/Naukri passwords
echo   3. Run: run_login.bat        (login to LinkedIn + Naukri once)
echo   4. Run: run_test.bat         (test with 3 applications)
echo   5. Run: setup_scheduler.bat  (schedule daily at 9 AM)
echo.
pause
