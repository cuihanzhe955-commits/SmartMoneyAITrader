"""Velocity Terminal. Local-only HTTP application, Python 3.10+."""

import argparse
import csv
import html
import io
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from challenge.manager import action, create, finish, market_time, scan
from events.store import Store, encode
from market.feeds import public
from challenge.config import DEFAULT
from risk.limits import equity

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
DONE = ("COMPLETED", "STOPPED")


def worker(db):
    while True:
        time.sleep(0.015)
        with LOCK:
            s = db.load()
            if not s or s["lifecycle_status"] in DONE + ("CREATED",):
                continue
            now = market_time(s)
            replay = s["config"]["source"] == "history"
            if s["lifecycle_status"] in ("PAUSED", "ERROR"):
                with db.db:
                    if now >= s["deadline"]:
                        s["t"] = now
                        finish(db, s)
                    elif int(time.time()) != s["heartbeat"]:
                        s["heartbeat"] = int(time.time())
                        db.save(s)
                continue
            if now < s["next_scan"] and now < s["deadline"]:
                if int(time.time()) - s["heartbeat"] >= 2:
                    with db.db:
                        s["heartbeat"] = int(time.time())
                        db.save(s)
                continue
            token = (s["id"], s["next_scan"], s["lifecycle_status"])
        rows = None
        if not replay:
            try:
                rows = public(now)
            except Exception:
                rows = {}
        with LOCK, db.db:
            s = db.load()
            if token != (s["id"], s["next_scan"], s["lifecycle_status"]):
                continue
            try:
                # Commit each cursor with its fills. Replay visits each closed bar in sequence.
                t = min(s["next_scan"], s["deadline"]) if replay else market_time(s)
                db.db.execute("SAVEPOINT cycle")
                scan(db, s, t, rows, manage=t < s["deadline"])
                if t >= s["deadline"]:
                    finish(db, s)
                elif replay:
                    step = s["config"]["interval"]
                    following = (t // 60 + 1) * 60
                    s["next_scan"] = min(s["deadline"], t + max(step, following - t))
                    db.save(s)
                db.db.execute("RELEASE cycle")
            except Exception as e:
                db.db.execute("ROLLBACK TO cycle")
                db.db.execute("RELEASE cycle")
                s = db.load()
                s["lifecycle_status"] = "ERROR"
                s["latest"] = str(e)
                db.record("system_events", s, "ERROR", str(e))
                db.save(s)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, v, kind="application/json", status=200, name=None):
        raw = (
            v
            if isinstance(v, bytes)
            else (encode(v) if kind == "application/json" else v).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        if name:
            self.send_header(
                "Content-Disposition", 'attachment; filename="' + name + '"'
            )
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urlsplit(self.path)
        p = url.path
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if p in ("/", "/app.js", "/style.css"):
                f = ROOT / "web" / ("index.html" if p == "/" else p[1:])
                return self.send(
                    f.read_bytes(), mimetypes.guess_type(str(f))[0] or "text/plain"
                )
            with LOCK:
                db = self.server.store
                s = db.load(int(q["id"]) if q.get("id") else None)
                if p == "/api/state":
                    if not s:
                        return self.send(dict(state=None, defaults=DEFAULT))
                    cid = s["id"]
                    now = s["t"] if s["lifecycle_status"] in DONE else market_time(s)
                    curve = db.entries("portfolio_snapshots", cid, 1500)
                    report = db.entries("reports", cid, 1)
                    return self.send(
                        dict(
                            state=s,
                            defaults=DEFAULT,
                            nav=equity(s),
                            now=now,
                            curve=[[r["t"], r["data"]["nav"]] for r in reversed(curve)],
                            marks=[
                                [r["t"], r["kind"]] for r in db.entries("fills", cid)
                            ]
                            + [
                                [r["t"], "BREAKER"]
                                for r in db.entries(
                                    "system_events", cid, kind="BREAKER"
                                )
                            ],
                            report=report[0]["data"] if report else None,
                        )
                    )
                if p == "/api/history":
                    return self.send(
                        [
                            dict(
                                id=v["id"],
                                status=v["lifecycle_status"],
                                nav=equity(v),
                                source=v["config"]["source"],
                            )
                            for v in (
                                json.loads(r[0])
                                for r in db.db.execute(
                                    "SELECT state FROM challenges ORDER BY id DESC"
                                )
                            )
                        ]
                    )
                if not s:
                    raise ValueError("尚未创建挑战")
                cid = s["id"]
                if p == "/api/events":
                    table = {
                        "events": "system_events",
                        "orders": "simulated_orders",
                        "decisions": "decisions",
                    }[q.get("table", "events")]
                    return self.send(
                        db.entries(
                            table,
                            cid,
                            21,
                            max(0, int(q.get("page", 0))) * 20,
                            q.get("symbol", ""),
                            q.get("kind", ""),
                        )
                    )
                if p == "/api/order":
                    r = db.db.execute(
                        "SELECT * FROM simulated_orders WHERE challenge_id=? AND id=?",
                        (cid, int(q["order"])),
                    ).fetchone()
                    return self.send(
                        dict(dict(r), data=json.loads(r["data"])) if r else {}
                    )
                if p.startswith("/export/"):
                    fmt = p.split("/")[-1]
                    report = db.entries("reports", cid, 1)[0]["data"]
                    timeline = list(reversed(db.entries("system_events", cid)))
                    name = f"challenge-{cid}.{fmt}"
                    if fmt == "json":
                        return self.send(
                            encode(dict(report=report, timeline=timeline)).encode(),
                            "application/json",
                            name=name,
                        )
                    if fmt == "csv":
                        out = io.StringIO()
                        w = csv.writer(out)
                        w.writerow(["report", encode(report)])
                        w.writerow(
                            [
                                "id",
                                "market_time",
                                "symbol",
                                "event",
                                "summary",
                                "detail",
                            ]
                        )
                        for r in timeline:
                            w.writerow(
                                [
                                    r["id"],
                                    r["t"],
                                    r["symbol"],
                                    r["kind"],
                                    r["summary"],
                                    encode(r["data"]),
                                ]
                            )
                        return self.send(
                            out.getvalue().encode("utf-8-sig"), "text/csv", name=name
                        )
                    if fmt == "html":
                        body = (
                            "<!doctype html><meta charset=utf-8><title>挑战报告</title><style>body{font:16px system-ui;max-width:960px;margin:40px auto}pre{white-space:pre-wrap}</style><h1>24小时翻倍挑战 · 结算报告</h1><p>"
                            + report["notice"]
                            + "</p><pre>"
                            + html.escape(
                                json.dumps(report, ensure_ascii=False, indent=2)
                            )
                            + "</pre><h2>决策时间线</h2>"
                        )
                        body += "".join(
                            "<details><summary>"
                            + html.escape(
                                time.strftime("%H:%M:%S", time.gmtime(r["t"]))
                                + " UTC · "
                                + r["symbol"]
                                + " "
                                + r["kind"]
                                + " "
                                + r["summary"]
                            )
                            + "</summary><pre>"
                            + html.escape(encode(r["data"]))
                            + "</pre></details>"
                            for r in timeline
                        )
                        return self.send(body, "text/html", name=name)
            self.send({"error": "未找到"}, status=404)
        except (ValueError, KeyError, IndexError) as e:
            self.send({"error": str(e)}, status=400)

    def do_POST(self):
        try:
            if (
                self.headers.get("Content-Type") != "application/json"
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
            ):
                raise ValueError("仅允许本地页面提交")
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size < 20000:
                raise ValueError("请求长度无效")
            data = json.loads(self.rfile.read(size))
            db = self.server.store
            with LOCK, db.db:
                if self.path == "/api/create":
                    s = create(db, data)
                elif self.path.startswith("/api/action/"):
                    s = db.load()
                    if not s or data.get("id") != s["id"]:
                        raise ValueError("当前挑战已变化")
                    action(db, s, self.path.split("/")[-1])
                else:
                    raise ValueError("未知操作")
            self.send({"id": s["id"]})
        except (TypeError, KeyError, ValueError) as e:
            self.send({"error": str(e)}, status=400)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8784)
    p.add_argument("--db", default=str(ROOT / "runtime/challenges.sqlite3"))
    a = p.parse_args()
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    http = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    # The OS releases this lock on process death, including abrupt shutdown.
    owner = open(str(Path(a.db).resolve()) + ".lock", "a+b")
    owner.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    http.store = Store(a.db)
    threading.Thread(target=worker, args=(http.store,), daemon=True).start()
    print(f"Velocity Terminal  http://127.0.0.1:{a.port}", flush=True)
    http.serve_forever()


if __name__ == "__main__":
    main()
