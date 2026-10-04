@echo off
REM Test run — applies to 3 jobs only
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo.
echo Running dry-run first (no applications)...
echo.
python main.py --dry-run
echo.
echo ========================================
echo   Dry run complete! Check output above.
echo   Now applying to 3 jobs as a test...
echo ========================================
echo.
python main.py --limit 3
echo.
echo Done! Check your LinkedIn/Naukri to verify applications went through.
pause
