@echo off
rem Starts Django and the website + tunnel, each in its own window. Double-click or run: start.bat
rem Extra options are passed on, for example: start.bat -Stop   or   start.bat -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
