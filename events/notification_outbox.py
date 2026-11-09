"""Durable notification intents and dispatch state, no implicit sending.

Future producers must enqueue outside trading/protection transactions. The worker
tracks attempts; actual channel adapters and delivery verification remain separate.
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
                    return dict(self._status(db,key), duplicate=True)
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
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_dispatch' AND type='table'").fetchone():
                    rows=db.execute("""SELECT o.id,o.created_at,o.event_json FROM notification_outbox o
                        LEFT JOIN notification_dispatch d ON d.id=o.id WHERE d.id IS NULL OR d.state='RETRY'
                        ORDER BY o.created_at,o.id LIMIT ?""",(limit,)).fetchall()
                else:
                    rows = db.execute("SELECT id,created_at,event_json FROM notification_outbox WHERE state='PENDING' ORDER BY created_at,id LIMIT ?", (limit,)).fetchall()
                result=[]
                for r in rows:
                    status=self._status(db,r[0])
                    if status['state'] in ('PENDING','RETRY'):
                        result.append(dict(status,created_at=r[1],event=json.loads(r[2])))
            return result
        except sqlite3.Error:
            raise ValueError("通知队列读取暂不可用，请稍后重试") from None

    @staticmethod
    def _status(db,key):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_dispatch' AND type='table'").fetchone():
            row=db.execute('SELECT state,attempts,next_try,receipt,error FROM notification_dispatch WHERE id=?',(key,)).fetchone()
            if row:
                return dict(id=key,state=row[0],attempts=row[1],next_try=row[2],receipt=row[3],error=row[4],delivery_verified=False)
        return dict(id=key,state='PENDING',delivery_verified=False)

    def status(self,key):
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            if not db.execute('SELECT 1 FROM notification_outbox WHERE id=?',(key,)).fetchone():
                raise ValueError('通知记录不存在')
            return self._status(db,key)

    def claim(self,token,timeout,max_attempts,channel=None):
        """Expired SENDING is UNKNOWN, never silently sent again after restart."""
        if not self.path.exists():return None
        try:
            with closing(sqlite3.connect(self.path,timeout=.1)) as db,db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_outbox' AND type='table'").fetchone():return None
                db.execute('BEGIN IMMEDIATE')
                db.execute("""CREATE TABLE IF NOT EXISTS notification_dispatch(
                    id TEXT PRIMARY KEY REFERENCES notification_outbox(id),
                    state TEXT NOT NULL CHECK(state IN ('SENDING','RETRY','ACKNOWLEDGED','FAILED','UNKNOWN')),
                    attempts INTEGER NOT NULL,max_attempts INTEGER NOT NULL,token TEXT NOT NULL,
                    lease_until REAL NOT NULL,next_try REAL NOT NULL,receipt TEXT NOT NULL,error TEXT NOT NULL)""")
                now=self.clock()
                db.execute("UPDATE notification_dispatch SET state='UNKNOWN',error='发送进程中断或租约过期，需核对结果；未自动重发' WHERE state='SENDING' AND lease_until<=?",(now,))
                row=db.execute("""SELECT o.id,o.event_json,d.attempts,d.max_attempts FROM notification_outbox o
                    LEFT JOIN notification_dispatch d ON d.id=o.id
                    WHERE (d.id IS NULL OR (d.state='RETRY' AND d.next_try<=?))
                    AND (? IS NULL OR json_extract(o.event_json,'$.channel')=?)
                    ORDER BY o.created_at,o.id LIMIT 1""",(now,channel,channel)).fetchone()
                if not row:return None
                attempt=(row[2] or 0)+1;limit=row[3] or max_attempts
                if attempt>limit:
                    db.execute("UPDATE notification_dispatch SET state='FAILED',error='通知重试预算已用完' WHERE id=?",(row[0],))
                    return None
                db.execute("""INSERT INTO notification_dispatch VALUES(?,'SENDING',?,?,?, ?,0,'','')
                    ON CONFLICT(id) DO UPDATE SET state='SENDING',attempts=excluded.attempts,
                    token=excluded.token,lease_until=excluded.lease_until,error=''""",
                    (row[0],attempt,limit,token,now+timeout))
                return dict(id=row[0],event=json.loads(row[1]),token=token,lease_until=now+timeout)
        except sqlite3.Error:
            raise ValueError('通知工作器数据库忙；未确认领取，不启动发送') from None

    def finish(self,key,token,state,receipt=''):
        if state not in ('ACKNOWLEDGED','RETRY','FAILED','UNKNOWN'):raise ValueError('通知终态无效')
        try:
            with closing(sqlite3.connect(self.path,timeout=.1)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute("SELECT attempts,max_attempts,lease_until FROM notification_dispatch WHERE id=? AND token=? AND state='SENDING'",(key,token)).fetchone()
                if not row:return False
                now=self.clock()
                if now>=row[2]:state='UNKNOWN';receipt=''
                if state=='RETRY' and row[0]>=row[1]:state='FAILED'
                error={'ACKNOWLEDGED':'','RETRY':'确认未受理，等待有限重试','FAILED':'明确拒绝或通知重试预算耗尽','UNKNOWN':'结果未知，未自动重发，请核对远端记录'}[state]
                retry=now+min(300,5*2**(row[0]-1)) if state=='RETRY' else 0
                db.execute('UPDATE notification_dispatch SET state=?,next_try=?,receipt=?,error=? WHERE id=? AND token=?',
                    (state,retry,receipt,error,key,token))
                return True
        except sqlite3.Error:
            raise ValueError('通知结果暂未持久保存；不自动再次提交该消息') from None
