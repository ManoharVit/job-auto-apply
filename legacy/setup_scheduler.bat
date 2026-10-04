@echo off
REM ============================================================
REM setup_scheduler.bat — Creates a Windows Task Scheduler task
REM that runs the bot every day at 9:00 AM
REM Run as Administrator!
REM ============================================================

echo.
echo ========================================
echo   Setting up Daily Scheduler (9 AM)
echo ========================================
echo.

set BOT_DIR=%~dp0
set TASK_NAME=JobAutoApplyBot

REM Delete existing task if any
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

REM Create scheduled task: daily at 9:00 AM
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%BOT_DIR%run_daily.bat\"" ^
    /sc daily ^
    /st 09:00 ^
    /rl HIGHEST ^
    /f

if %errorlevel% equ 0 (
    echo.
    echo [OK] Scheduled task created successfully!
    echo      Name:     %TASK_NAME%
    echo      Schedule: Every day at 9:00 AM
    echo      Script:   %BOT_DIR%run_daily.bat
    echo.
    echo To verify:  schtasks /query /tn "%TASK_NAME%"
    echo To delete:  schtasks /delete /tn "%TASK_NAME%" /f
    echo To run now: schtasks /run /tn "%TASK_NAME%"
) else (
    echo.
    echo [ERROR] Failed to create scheduled task.
    echo         Try running this script as Administrator.
)

echo.
pause
