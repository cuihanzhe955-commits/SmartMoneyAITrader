@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "APP_PY="
set "APP_FLAG="

rem Prefer the project venv, then Python Launcher, then a normal PATH interpreter.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if not errorlevel 1 set "APP_PY=.venv\Scripts\python.exe"
)
for %%V in (3.11 3.12 3.13 3.14) do (
    if not defined APP_PY (
        py -%%V -c "import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
        if not errorlevel 1 (
            set "APP_PY=py"
            set "APP_FLAG=-%%V"
        )
    )
)
if not defined APP_PY (
    py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "APP_PY=py"
        set "APP_FLAG=-3"
    )
)
if not defined APP_PY (
    python -c "import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if not errorlevel 1 set "APP_PY=python"
)
if not defined APP_PY (
    echo [错误] 未检测到可用的 Python 3.11 或以上版本。
    echo 请安装 Python 3.11 及以上版本并勾选 Add python.exe to PATH。
    echo 官方下载：https://www.python.org/downloads/windows/
    echo 安装完成后关闭命令行窗口，重新双击 start.bat。
    echo 本项目运行无需安装 Git 或 Node.js，Git 只用于克隆源码。
    goto :failure
)

if /I "%APP_PY%"=="py" (
    py %APP_FLAG% -B "scripts\launcher.py" %*
) else (
    "%APP_PY%" -B "scripts\launcher.py" %*
)
if errorlevel 1 goto :failure
exit /b 0

:failure
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" set "RESULT=2"
echo.
echo [提示] 启动未完成。请查看上方错误提示，必要时截图反馈。
if not "%SMART_MONEY_NO_PAUSE%"=="1" pause
exit /b %RESULT%
