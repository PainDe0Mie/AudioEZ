@echo off
title AudioEz - Launcher
cd /d "%~dp0"

cls
echo.
echo [AudioEz] Start as ADMINISTRATOR if this is your fist time starting or you need to update equalizer apo!
echo.
echo.
echo [AudioEz] Starting..
echo.

python ./main.py


echo.
echo [AudioEz] Finish.

pause > nul