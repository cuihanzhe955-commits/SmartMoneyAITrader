@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
REM 工具从仓库 tools\git_sync 中运行，默认主工程为上两级目录。
if not defined SMARTMONEY_PROJECT set "SMARTMONEY_PROJECT=%~dp0..\.."
for %%I in ("%SMARTMONEY_PROJECT%") do set "SMARTMONEY_PROJECT=%%~fI"
cd /d "%~dp0"
if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "PATH=%ProgramFiles(x86)%\Git\cmd;%PATH%"
echo.
echo ==============================================================
echo   Smart Money AI Trader - 中文一键安全同步
 echo ==============================================================
echo   主工程：%SMARTMONEY_PROJECT%
echo   操作：本地备份 / 双端比较 / 离线测试 / 安全更新
 echo   注意：冲突或测试失败时自动停止，不会强制覆盖！
echo.
REM 优先使用主工程自己的虚拟环境，避免系统 Python 版本和依赖不一致。
if exist "%SMARTMONEY_PROJECT%\.venv\Scripts\python.exe" (
    "%SMARTMONEY_PROJECT%\.venv\Scripts\python.exe" "%~dp0smartmoney_sync.py" --mode sync --project "%SMARTMONEY_PROJECT%"
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python "%~dp0smartmoney_sync.py" --mode sync --project "%SMARTMONEY_PROJECT%"
    ) else (
        py -3 "%~dp0smartmoney_sync.py" --mode sync --project "%SMARTMONEY_PROJECT%"
    )
)
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo 【同步已停止】请查看主工程同级目录 SmartMoneyAITrader_SYNC_BACKUPS 下的最新中文同步报告。
  echo 没有执行强制推送。请先解决报告中的问题，再重新运行。
) else (
  echo 【运行结束】请查看最新中文同步报告，确认实际是否需要推送。
)
echo.
pause
exit /b %RESULT%