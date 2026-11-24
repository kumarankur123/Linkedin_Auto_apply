@echo off
cd /d "%~dp0"
echo Cleaning up any stale driver processes...
taskkill /F /IM chromedriver.exe >nul 2>&1
echo Starting LinkedIn AI Job Applier...
.\.venv\Scripts\python.exe runAiBot.py
pause
