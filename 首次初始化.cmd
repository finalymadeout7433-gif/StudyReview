@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\initialize-new.ps1" %*
exit /b %errorlevel%
