@echo off
echo Starting MT5 Trader Companion...
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
python trader_companion\trader_app.py
pause
