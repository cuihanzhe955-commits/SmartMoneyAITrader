"""Durable notification intents only: no worker, transport or implicit sending.

Future producers must enqueue outside trading/protection transactions. Actual
delivery, retry policy and channel configuration are separate unimplemented work.
"""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from events.observations import canonical, digest


class NotificationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    product: Literal["spot", "event"]
    environment: Literal["paper", "reference_paper", "demo", "live"]
    event_type: Literal["forecast", "skip", "fill", "settlement", "error", "risk", "stopped", "test"]
    channel: Literal["feishu", "telegram"]
    account: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=4000)


class NotificationOutbox:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock

    def enqueue(self, intent: NotificationIntent):
        body = intent.model_dump()
        identity = {k: body[k] for k in ("provider", "product", "environment", "session_id",
                                        "event_id", "channel", "account", "target")}
        key, payload = digest(canonical(identity)), canonical(body)
        try:
            with closing(sqlite3.connect(self.path, timeout=.1)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""CREATE TABLE IF NOT EXISTS notification_outbox(
                    id TEXT PRIMARY KEY,created_at REAL NOT NULL,event_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state='PENDING'))""")
                old = db.execute("SELECT event_json FROM notification_outbox WHERE id=?", (key,)).fetchone()
                if old:
                    if old[0] != payload:
                        raise ValueError("相同通知事件与目的地的内容发生变化，未覆盖原记录")
                    return dict(id=key, duplicate=True, state="PENDING", delivery_verified=False)
                db.execute("INSERT INTO notification_outbox VALUES(?,?,?,'PENDING')", (key, self.clock(), payload))
            return dict(id=key, duplicate=False, state="PENDING", delivery_verified=False)
        except sqlite3.Error:
            raise ValueError("通知队列数据库忙或不可用；未确认入队，请稍后重试") from None

    def pending(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("通知读取数量应为1至100")
        if not self.path.exists():
            return []
        try:
            with closing(sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=.1)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_outbox' AND type='table'").fetchone():
                    return []
                rows = db.execute("SELECT id,created_at,event_json FROM notification_outbox WHERE state='PENDING' ORDER BY created_at,id LIMIT ?", (limit,)).fetchall()
            return [dict(id=r[0], created_at=r[1], event=json.loads(r[2]), state="PENDING", delivery_verified=False) for r in rows]
        except sqlite3.Error:
            raise ValueError("通知队列读取暂不可用，请稍后重试") from None
