@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-public.ps1" %*
exit /b %errorlevel%
