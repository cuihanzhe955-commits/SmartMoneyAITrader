@echo off
setlocal
cd /d "%~dp0"
call "%~dp0start.bat" --install-only
exit /b %ERRORLEVEL%
