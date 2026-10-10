@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup-public.ps1" %*
exit /b %errorlevel%
