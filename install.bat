@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; assert sys.version_info >= (3,11)" || (echo Python 3.11+ required & exit /b 1)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
exit /b %errorlevel%

