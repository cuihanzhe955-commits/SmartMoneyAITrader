"""Start the local terminal, or open its existing instance."""

import json
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parent
url = "http://127.0.0.1:8784"


def ready():
    try:
        with urlopen(url + "/api/state", timeout=1) as r:
            return "defaults" in json.load(r)
    except (OSError, ValueError):
        return False


if ready():
    webbrowser.open(url)
else:
    process = subprocess.Popen([sys.executable, str(root / "server.py")], cwd=root)
    try:
        for _ in range(80):
            if process.poll() is not None:
                raise SystemExit("服务未能启动，请检查端口 8784。")
            if ready():
                webbrowser.open(url)
                break
            time.sleep(0.1)
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
