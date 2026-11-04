import asyncio
import csv
import html
import io
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from typing import Literal
from terminal.runtime import Runtime, DONE, safe_error
from challenge.clock import market_time
from terminal.settings import AIConfig
from terminal.config import Session
from execution.live import pending
from risk.limits import equity
from events.store import encode
from ai.provider import Provider
from risk.parameters import RECOMMENDED

ROOT = Path(__file__).resolve().parents[1]


class Command(BaseModel):
    id: int
    cmd: Literal["start", "pause", "resume", "stop", "end", "step", "reconcile", "use_rules"]
    confirmation: str = ""


class Credentials(BaseModel):
    exchange: Literal["okx", "binance"]
    environment: Literal["demo", "live"]
    key: SecretStr
    secret: SecretStr
    passphrase: SecretStr = SecretStr("")


class AISetup(BaseModel):
    config: AIConfig
    key: SecretStr = SecretStr("")


class Import(BaseModel):
    name: str = Field(max_length=120)
    text: str = Field(max_length=12_000_000)


class Acceptance(BaseModel):
    id: int = Field(gt=0)


class ProtectionAction(BaseModel):
    id: int = Field(gt=0)
    action: Literal["create", "query", "cancel", "finalize"]
    client_id: str = Field(default="", max_length=32)
    symbol: str = Field(default="", max_length=16)
    stop_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)


def create_app(path=None):
    @asynccontextmanager
    async def lifespan(app):
        rt = Runtime(path or os.environ.get("SMART_MONEY_RUNTIME", ROOT / "runtime"))
        app.state.rt = rt
        # Enforce one scheduler per ledger even when the app starts on a second port.
        import msvcrt

        owner = open(rt.root / "terminal.lock", "a+b")
        owner.seek(0)
        msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
        rt.start_worker()
        try:
            yield
        finally:
            rt.shutdown()
            rt.db.db.close()
            owner.close()

    app = FastAPI(
        title="Smart Money AI Trader", lifespan=lifespan, docs_url=None, redoc_url=None
    )

    def rt():
        return app.state.rt

    @app.middleware("http")
    async def local(request, call_next):
        host = request.headers.get("host", "")
        if host.split(":")[0] not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"error": "本机服务"}, 403)
        if request.method != "GET" and (
            request.headers.get("sec-fetch-site") == "cross-site"
            or request.headers.get("origin", "http://" + host) != "http://" + host
            or not request.headers.get("content-type", "").startswith(
                "application/json"
            )
        ):
            return JSONResponse({"error": "来源不符"}, 403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(request, e):
        return JSONResponse({"error": safe_error(e)}, 400)

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def invalid_schema(request, e):
        return JSONResponse({"error": "配置无效：" + e.errors()[0]["msg"]}, 422)

    @app.get("/api/health")
    def health():
        return {
            "product": "Smart Money AI Trader",
            "version": "1.0 Beta",
            "database": rt().db.db.execute("SELECT 1").fetchone()[0] == 1,
        }

    @app.get("/api/protection-status")
    def protection_status():
        return rt().hosted_status()

    @app.post("/api/protection-action")
    def protection_action(x: ProtectionAction):
        result = rt().hosted_action(x.id, x.action, x.client_id, x.symbol, x.stop_price)
        return {k: result.get(k) for k in ("client_id", "stage", "released", "quantity", "symbol")}

    @app.get("/api/protection-report")
    def protection_report(id: int, client_id: str, before: int = 0):
        return rt().hosted_report(id, client_id, before)

    @app.post("/api/shutdown")
    def shutdown(body: dict):
        if not hasattr(app.state, "request_shutdown"):
            raise ValueError("请通过 Windows 启动器管理服务")
        with rt().lock, rt().db.db:
            s = rt().db.load()
            from execution.live import unresolved
            if unresolved(rt().db):
                raise ValueError("存在未核对订单，请先紧急停止并等待交易所回报")
            if (s and s["config"].get("execution", "paper") != "paper" and s["positions"]
                    and body.get("confirmation") != "已接管交易所持仓"):
                raise ValueError("仍有交易所持仓。退出后本地止损停止，请在终端核对并确认接管")
            if s and s["lifecycle_status"] in ("RUNNING", "DATA_STALE", "INITIALIZING"):
                rt().command(s["id"], "pause")
            rt().exit.set()
        app.state.request_shutdown()
        return {"ok": True}

    @app.get("/api/settings")
    def settings():
        return rt().vault.public()

    @app.get("/api/parameters")
    def parameters():
        return {key: {"name": name, "low": low, "high": high}
                for key, (name, low, high) in RECOMMENDED.items()}

    @app.post("/api/credentials")
    def keys(x: Credentials):
        values = {
            k: getattr(x, k).get_secret_value().strip()
            for k in ("key", "secret", "passphrase")
        }
        if (
            not values["key"]
            or not values["secret"]
            or x.exchange == "okx"
            and not values["passphrase"]
        ):
            raise ValueError("请填完整凭据")
        with rt().lock:
            s = rt().db.load()
            from execution.live import unresolved
            previous = [json.loads(row[0]) for row in rt().db.db.execute("SELECT state FROM challenges")]
            if unresolved(rt().db) or any(
                st["config"].get("exchange") == x.exchange and st["config"].get("execution") == x.environment
                and (st.get("positions") or st.get("needs_check")) for st in previous
            ):
                raise ValueError("有交易所持仓或未核对资金，无法更换交易凭据")
            if (
                s
                and s["lifecycle_status"] not in DONE
                and s["config"]["execution"] != "paper"
            ):
                raise ValueError("先结束当前交易所会话")
            rt().vault.update(x.exchange + "/" + x.environment, values)
            rt().clients.clear()
        return {"ok": True}

    @app.post("/api/ai")
    def ai(x: AISetup):
        key = x.key.get_secret_value() or rt().vault.values.get("ai_key", "")
        if not x.config.model or not key:
            raise ValueError("AI 模型和密钥不能为空")
        Provider(x.config.model_dump(), key)
        with rt().lock:
            if not x.key.get_secret_value() and x.config.base != rt().vault.values.get(
                "ai_config", {}
            ).get("base"):
                raise ValueError("更换服务地址时请重新输入对应密钥")
            rt().vault.update_many({"ai_key": key, "ai_config": x.config.model_dump()})
            with rt().db.db:
                state = rt().db.load()
                if state and state["lifecycle_status"] not in DONE and state["config"].get("engine") == "ai":
                    rt().invalidate_ai(state, "AI 配置变更，旧提案已作废")
                    state["ai_signature"] = None
                    rt().db.save(state)
        return {"ok": True}

    @app.post("/api/ai/test")
    def test_ai():
        cfg = rt().vault.values.get("ai_config")
        if not cfg:
            raise ValueError("请先保存 AI 连接配置")
        Provider(cfg, rt().vault.values.get("ai_key", "")).chat("只回复 OK", "连接测试")
        return {"ok": True}

    @app.post("/api/account/test")
    def test_account(x: dict):
        try:
            if x.get("execution") not in ("demo", "live"):
                raise ValueError("请选择账户环境")
            free, _ = rt().venue(x).balance()
            return {"free_usdt": free}
        except Exception as e:
            raise ValueError("账户读取失败 · " + safe_error(e)) from None

    @app.get("/api/datasets")
    def datasets():
        return [
            dict(r)
            for r in rt().db.db.execute(
                "SELECT id,name,start,end FROM datasets ORDER BY rowid DESC"
            )
        ]

    @app.post("/api/account/verify")
    def verify_account(x: Acceptance):
        from execution.health import inspect_session
        return inspect_session(rt(), x.id)

    @app.get("/api/account/verification")
    def account_verification(id: int):
        from execution.health import latest_report
        with rt().lock:
            return {"report": latest_report(rt(), id)}

    @app.post("/api/datasets")
    def add(x: Import):
        with rt().lock, rt().db.db:
            return {"id": rt().add_csv(x.name, x.text)}

    @app.post("/api/sessions")
    def new(x: Session):
        with rt().lock, rt().db.db:
            return {"id": rt().new(x)["id"], "warnings": x.warnings()}

    @app.post("/api/command")
    def command(x: Command):
        with rt().lock, rt().db.db:
            return {
                "status": rt().command(x.id, x.cmd, x.confirmation)["lifecycle_status"]
            }

    @app.get("/api/state")
    def state(id: int | None = None):
        with rt().lock:
            db = rt().db
            s = db.load(id)
            records = [
                json.loads(r[0])
                for r in db.db.execute("SELECT state FROM challenges ORDER BY id DESC")
            ]
            archive = [
                dict(
                    id=v["id"],
                    profile=v["config"].get("profile", "challenge"),
                    engine=v["config"].get("engine", "rules"),
                    source=v["config"]["source"],
                    execution=v["config"].get("execution", "paper"),
                    status=v["lifecycle_status"],
                    nav=equity(v),
                    roi=(equity(v) / v["config"]["capital"] - 1) * 100,
                )
                for v in records
            ]
            if not s:
                return dict(state=None, archive=archive)
            cid = s["id"]
            curve = list(reversed(db.entries("portfolio_snapshots", cid, 1500)))
            reports = db.entries("reports", cid, 1)
            return dict(
                state=s,
                now=(
                    s["t"]
                    if s["lifecycle_status"] in DONE or (
                        s["lifecycle_status"]=="PAUSED" and s["config"]["source"]!="public" and s["config"]["profile"]=="normal"
                    ) else market_time(s)
                ),
                nav=equity(s),
                archive=archive,
                curve=[[r["t"], r["data"]["nav"]] for r in curve],
                fills=db.entries("fills", cid, 100),
                events=db.entries("system_events", cid, 60),
                decisions=db.entries("decisions", cid, 30),
                report=reports[0]["data"] if reports else None,
                pending=pending(db, cid),
            )

    @app.get("/api/journal")
    def journal(
        id: int,
        table: Literal[
            "system_events", "decisions", "fills", "risk_checks"
        ] = "system_events",
        page: int = 0,
        symbol: str = "",
        kind: str = "",
    ):
        with rt().lock:
            return rt().db.entries(table, id, 31, max(page, 0) * 30, symbol, kind)

    @app.get("/api/export/{id}/{fmt}")
    def export(id: int, fmt: Literal["html", "csv", "json"]):
        with rt().lock:
            reports = rt().db.entries("reports", id, 1)
            if not reports:
                raise ValueError("请先结束会话")
            r = reports[0]["data"]
            events = list(reversed(rt().db.entries("system_events", id)))
        if fmt == "json":
            body = encode(dict(report=r, events=events))
            mime = "application/json"
        elif fmt == "html":
            body = (
                "<!doctype html><meta charset=utf-8><title>交易实验报告</title><h1>交易实验报告</h1><pre>"
                + html.escape(json.dumps(r, ensure_ascii=False, indent=2))
                + "</pre>"
                + "".join(
                    "<details><summary>"
                    + html.escape(f"{e['t']} · {e['kind']} · {e['summary']}")
                    + "</summary><pre>"
                    + html.escape(encode(e["data"]))
                    + "</pre></details>"
                    for e in events
                )
            )
            mime = "text/html"
        else:
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["report", encode(r)])
            w.writerow(["UTC 秒", "币种", "事件", "解释", "数据"])
            for e in events:
                w.writerow(
                    [
                        e["t"],
                        e["symbol"],
                        e["kind"],
                        "'" + e["summary"],
                        encode(e["data"]),
                    ]
                )
            body = "\ufeff" + out.getvalue()
            mime = "text/csv"
        return Response(
            body,
            media_type=mime,
            headers={"Content-Disposition": f"attachment; filename=session-{id}.{fmt}"},
        )

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        host = sock.headers.get("host", "")
        if (
            host.split(":")[0] not in ("127.0.0.1", "localhost")
            or sock.headers.get("origin") != "http://" + host
        ):
            return await sock.close(code=1008)
        await sock.accept()
        try:
            while True:
                with rt().lock:
                    event=rt().db.db.execute('SELECT coalesce(max(id),0) FROM system_events').fetchone()[0]
                await sock.send_json({"heartbeat": int(time.time()),"event":event})
                await asyncio.sleep(2)
        except (WebSocketDisconnect, RuntimeError):
            pass

    dist = ROOT / "frontend/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="terminal")
    return app


app = create_app()
