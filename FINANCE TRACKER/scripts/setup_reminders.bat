@echo off
rem Checks reminders every 15 minutes while this PC is on, even when the app is closed.
rem Run with "remove" to turn it off:  setup_reminders.bat remove
set "TASK=Money Tracker reminders"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"

if /i "%~1"=="remove" (
  schtasks /Delete /TN "%TASK%" /F
  pause
  exit /b
)

set "PYW="
for /f "delims=" %%p in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%p"
if not defined PYW (
  echo Python was not found. Install Python from https://www.python.org first.
  pause
  exit /b 1
)

schtasks /Create /F /SC MINUTE /MO 15 /TN "%TASK%" /TR "\"%PYW%\" \"%ROOT%\server\server.py\" --check"
if errorlevel 1 (
  echo Could not create the scheduled task.
) else (
  echo Done. Reminders will be checked every 15 minutes while this PC is on.
)
pause
