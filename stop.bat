@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
 ".venv\Scripts\python.exe" -B terminal_host.py --stop %*
) else (
 python -B terminal_host.py --stop %*
)

