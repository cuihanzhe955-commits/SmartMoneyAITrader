"""Start, kill and restart the actual HTTP worker during an accelerated market day."""

import json
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:18785"


def request(path, body=None):
    r = Request(
        URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    return json.load(urlopen(r, timeout=10))


def boot(path):
    p = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py"), "--port", "18785", "--db", str(path)]
    )
    for _ in range(50):
        try:
            request("/api/state")
            return p
        except OSError:
            time.sleep(0.1)
    p.terminate()
    raise RuntimeError("server did not start")


def run():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "db"
        p = boot(path)
        try:
            request("/api/create", dict(consent=True, speed=3600, settlement="close"))
            request("/api/action/start", dict(id=1))
            time.sleep(4)
            p.kill()
            p.wait()
            p = boot(path)
            until = time.time() + 100
            while time.time() < until:
                time.sleep(1)
                r = request("/api/state")
                if r["report"]:
                    break
            assert r["report"] and r["state"]["lifecycle_status"] == "COMPLETED"
            assert (
                r["report"]["fills"] == 276
                and abs(r["report"]["nav"] - 8.775586350592897) < 1e-8
            ), r["report"]
            with closing(sqlite3.connect(path)) as db:
                assert (
                    db.execute("SELECT count(*) FROM market_snapshots").fetchone()[0]
                    == 1441
                )
            print(
                "PASS HTTP worker reached 24h automatically after process kill and restart; identical 276 fills and NAV."
            )
        finally:
            p.terminate()
            p.wait()


if __name__ == "__main__":
    run()
