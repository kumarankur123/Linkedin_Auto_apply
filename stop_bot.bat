@echo off
echo ========================================================
echo Stopping LinkedIn Job Applier Bot and Chrome drivers...
echo ========================================================
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM chromedriver.exe /T >nul 2>&1
echo.
echo [DONE] Bot processes terminated cleanly!
echo ========================================================
timeout /t 3
