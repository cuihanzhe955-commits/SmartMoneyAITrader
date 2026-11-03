@echo off
setlocal
cd /d "%~dp0"
set "APP_PY=python"
if exist ".venv\Scripts\python.exe" set "APP_PY=.venv\Scripts\python.exe"
"%APP_PY%" -c "import sys,ccxt,uvicorn,win32crypt,fastapi,pydantic,websockets; assert sys.version_info >= (3,11) and ccxt.__version__=='4.5.91' and pydantic.VERSION.startswith('2.')" >nul 2>nul
if errorlevel 1 (
 call install.bat
 if errorlevel 1 exit /b 1
 set "APP_PY=.venv\Scripts\python.exe"
)
"%APP_PY%" -B terminal_host.py %*
if errorlevel 1 pause

