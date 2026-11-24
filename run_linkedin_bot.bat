@echo off
cd /d "%~dp0"
echo ========================================================
echo   Starting LinkedIn AI Auto Job Applier
echo ========================================================
echo.
.\.venv\Scripts\python.exe runAiBot.py
if errorlevel 1 (
    echo.
    echo Bot exited with an error. Check logs/log.txt for details.
)
pause
