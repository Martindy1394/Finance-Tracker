@echo off
rem Gives an account a temporary password (the user chooses a new one when logging in). Data is kept.
rem Use this if the admin forgot their password and Telegram is not connected.
cd /d "%~dp0.."
set "USERNAME_TO_RESET="
set /p "USERNAME_TO_RESET=Username to reset (press Enter for the admin): "
python -B -X utf8 "%~dp0..\server\server.py" --reset-password %USERNAME_TO_RESET%
pause
