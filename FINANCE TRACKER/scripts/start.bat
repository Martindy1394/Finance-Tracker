@echo off
rem Starts Money Tracker: runs the server (keep its window open) and opens the app in your browser
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3 from https://www.python.org and run start.bat again.
  pause
  exit /b 1
)

rem If the server stops with an error, its window stays open so the message can be read
start "Money Tracker (keep open)" /min cmd /c "python -X utf8 "%~dp0..\server\server.py" || (echo. & echo Money Tracker stopped because of the error above. & pause)"
