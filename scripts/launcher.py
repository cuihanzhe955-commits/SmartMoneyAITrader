"""Windows source-edition bootstrap. No external dependencies before setup.

Only opens an existing local instance, installs pinned Python dependencies into
this project's .venv, or starts the original terminal_host.py. It never creates
or starts a trading session.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
REQUIREMENTS = ROOT / "requirements.txt"
PRODUCT = "Smart Money AI Trader"

# Executed by the *project* environment, not by this bootstrap interpreter.
VERIFY_PACKAGES = r'''
import importlib
from importlib.metadata import version
import sys
from pathlib import Path
for line in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if "==" not in line:
        sys.exit(2)
    package, expected = line.split("==", 1)
    if version(package.strip()) != expected.strip():
        sys.exit(3)
for module in ("fastapi", "uvicorn", "websockets", "pydantic", "ccxt", "win32crypt"):
    importlib.import_module(module)
'''


def announce(message: str) -> None:
    print(message, flush=True)


def status(port: int) -> str:
    """Return 'ours', 'occupied' or 'free' without sending mutating requests."""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urlopen(url, timeout=1.0) as response:
            document = json.loads(response.read(4096))
        if isinstance(document, dict) and document.get("product") == PRODUCT:
            return "ours"
    except (OSError, URLError, ValueError, UnicodeDecodeError, TimeoutError):
        pass
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return "occupied"
    except OSError:
        return "free"


def environment_ok(python: Path) -> bool:
    try:
        outcome = subprocess.run(
            [str(python), "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=15,
        )
        return outcome.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_venv() -> bool:
    if not VENV_PY.is_file():
        if VENV.exists():
            announce("[错误] .venv 文件夹不完整。为了保护原文件，启动器不会自动删除它。")
            announce("请先备份或重命名 .venv 文件夹，然后重新启动。")
            return False
        announce("[初始化] 首次运行，正在创建项目专用的 Python 虚拟环境 .venv …")
        try:
            create = subprocess.run([sys.executable, "-m", "venv", str(VENV)], cwd=ROOT, check=False)
        except OSError as exc:
            announce(f"[错误] 无法创建虚拟环境：{exc}")
            return False
        if create.returncode != 0:
            announce("[错误] 虚拟环境创建失败，请确认 Python 的 venv/pip 组件可用、磁盘空间充足。")
            return False
    if not environment_ok(VENV_PY):
        announce("[错误] 项目 .venv 内的 Python 无法运行或版本低于 3.11。")
        announce("请先备份或重命名 .venv，再运行 start.bat；不会自动删除原环境。")
        return False
    return True


def dependencies_ok() -> bool:
    try:
        proc = subprocess.run(
            [str(VENV_PY), "-c", VERIFY_PACKAGES, str(REQUIREMENTS)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_dependencies() -> bool:
    if not REQUIREMENTS.is_file():
        announce("[错误] 找不到 requirements.txt，请检查项目是否完整下载。")
        return False
    if dependencies_ok():
        announce("[检查] 依赖版本正确，无需重复安装。")
        return True
    announce("[安装] 正在将项目依赖安装到 .venv（首次运行需要网络）…")
    announce("[提示] 只安装项目 requirements.txt 中指定的依赖，不修改系统 Python。")
    try:
        proc = subprocess.run(
            [str(VENV_PY), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            cwd=ROOT, check=False,
        )
    except OSError as exc:
        announce(f"[错误] 无法运行 pip：{exc}")
        return False
    if proc.returncode != 0:
        announce("[错误] 依赖安装失败。请检查网络连接、磁盘空间和上方 pip 报错信息。")
        announce("可关闭其他 Python 进程后重试；无需重新下载整个项目。")
        return False
    if not dependencies_ok():
        announce("[错误] 安装后依赖仍未通过检查。请保留窗口中的报错信息供排查。")
        return False
    announce("[完成] 项目依赖安装成功。")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smart Money AI Trader 智能启动器")
    parser.add_argument("--install-only", action="store_true", help="只检查并安装依赖，不启动服务")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--port", type=int, default=8785, help="本地服务端口，默认 8785")
    parser.add_argument("--instance-id")
    parser.add_argument("--ready-file")
    parsed = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        announce("[错误] 需要 Python 3.11 或以上。官方下载：https://www.python.org/downloads/windows/")
        return 2
    if not (0 <= parsed.port <= 65535) or (parsed.port == 0 and not (parsed.instance_id and parsed.ready_file)):
        parser.error("--port 必须在 1 至 65535 之间")

    os.chdir(ROOT)
    if not parsed.install_only and not parsed.instance_id:
        check = status(parsed.port)
        if check == "ours":
            announce(f"[就绪] 检测到已运行的 {PRODUCT}：http://127.0.0.1:{parsed.port}")
            announce("[提示] 不会启动第二个进程；请确认这是你想使用的项目副本。")
            if not parsed.no_browser:
                webbrowser.open(f"http://127.0.0.1:{parsed.port}")
            return 0
        if check == "occupied":
            announce(f"[错误] 本机端口 {parsed.port} 已被其他服务占用，不能安全启动。")
            announce("请先确定占用端口的程序；启动器不会强制终止其他进程或自动切换端口。")
            return 3

    if not ensure_venv() or not ensure_dependencies():
        return 4
    if parsed.install_only:
        announce("[完成] 环境检查通过。未启动工作台或交易会话。")
        return 0

    command = [str(VENV_PY), "-B", str(ROOT / "terminal_host.py")]
    if parsed.no_browser:
        command.append("--no-browser")
    command.extend(["--port", str(parsed.port)])
    if parsed.instance_id:
        command.extend(["--instance-id", parsed.instance_id])
    if parsed.ready_file:
        command.extend(["--ready-file", parsed.ready_file])
    announce(f"[启动] 工作台地址：http://127.0.0.1:{parsed.port}")
    announce("[提示] 请保持此窗口打开；仅打开工作台不会主动创建交易会话。")
    try:
        proc = subprocess.run(command, cwd=ROOT, check=False)
    except KeyboardInterrupt:
        announce("[提示] 已收到中断请求；如涉及真实持仓，请先在工作台核对并使用 stop.bat 安全退出。")
        return 130
    except OSError as exc:
        announce(f"[错误] 后端进程无法启动：{exc}")
        return 5
    if proc.returncode != 0:
        announce(f"[错误] 后端退出，退出码 {proc.returncode}。请检查上方详细报错。")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
