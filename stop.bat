@echo off
rem Stops Django, the website and the tunnel that start.bat opened.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Stop
pause
