@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-public.ps1" %*
exit /b %errorlevel%
