@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
REM 仅审计：备份 + fetch + 比较，不执行合并、提交和推送。
if not defined SMARTMONEY_PROJECT set "SMARTMONEY_PROJECT=%~dp0..\.."
for %%I in ("%SMARTMONEY_PROJECT%") do set "SMARTMONEY_PROJECT=%%~fI"
cd /d "%~dp0"
if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "PATH=%ProgramFiles(x86)%\Git\cmd;%PATH%"
echo.
echo ==============================================================
echo   Smart Money AI Trader - 中文安全检查（不推送）
echo ==============================================================
echo   主工程：%SMARTMONEY_PROJECT%
echo   不会合并、提交、快进更新、推送或强制覆盖。
echo.
REM 优先使用主工程自己的虚拟环境，避免系统 Python 版本和依赖不一致。
if exist "%SMARTMONEY_PROJECT%\.venv\Scripts\python.exe" (
    "%SMARTMONEY_PROJECT%\.venv\Scripts\python.exe" "%~dp0smartmoney_sync.py" --mode audit --project "%SMARTMONEY_PROJECT%"
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python "%~dp0smartmoney_sync.py" --mode audit --project "%SMARTMONEY_PROJECT%"
    ) else (
        py -3 "%~dp0smartmoney_sync.py" --mode audit --project "%SMARTMONEY_PROJECT%"
    )
)
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo 【检查提示】发现需要处理的情况，请阅读最新中文同步报告。
) else (
  echo 【检查完成】只生成了备份与报告，未修改 Git 工作分支。
)
echo.
pause
exit /b %RESULT%