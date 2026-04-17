@echo off
REM Launch Chrome with remote debugging enabled for FundedNext scraping
REM This will open Chrome with your existing profile so you stay logged in

echo Closing existing Chrome instances...
taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo Starting Chrome with remote debugging on port 9444...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9444 --restore-last-session

echo.
echo Chrome started with remote debugging on port 9444
echo Navigate to https://app.fundednext.com/accounts if not already open
echo Then run: python trader_companion\fundednext.py --test --port 9444
pause
