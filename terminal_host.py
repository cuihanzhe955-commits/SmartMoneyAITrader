import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uvicorn
from terminal.api import app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", default=8785, type=int)
    a = parser.parse_args()
    url = f"http://127.0.0.1:{a.port}"
    if a.stop:
        try:
            req = Request(
                url + "/api/shutdown",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            print(urlopen(req, timeout=10).read().decode())
        except HTTPError as e:
            print(e.read().decode())
            raise SystemExit(1)
        except OSError:
            print("服务未运行。")
        return

    def ready():
        try:
            return (
                json.load(urlopen(url + "/api/health", timeout=0.6)).get("product")
                == "Smart Money AI Trader"
            )
        except (OSError, ValueError):
            return False

    if ready():
        if not a.no_browser:
            webbrowser.open(url)
        return
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=a.port, log_level="warning", access_log=False
        )
    )
    app.state.request_shutdown = lambda: setattr(server, "should_exit", True)

    def open_ready():
        for _ in range(80):
            if ready():
                print("Smart Money AI Trader " + url, flush=True)
                if not a.no_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.1)

    threading.Thread(target=open_ready, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
