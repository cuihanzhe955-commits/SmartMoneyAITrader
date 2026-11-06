"""Append-only event research snapshots in a logically separate table.

No cash ledger, positions, fills, settlement or trading authority. Network
reads complete before the short SQLite transaction; never take Runtime.lock.
"""
from contextlib import closing
import hashlib
import json
import sqlite3
import time
from pydantic import Field
from market.event_costs import CostQuery


class CaptureQuery(CostQuery):
    request_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ObservationJournal:
    def __init__(self, path, details, clock=time.time):
        self.path, self.details, self.clock = path, details, clock

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=.1)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _exists(db):
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_research_observations'").fetchone() is not None

    @staticmethod
    def _decode(row):
        if digest(row["data"]) != row["sha256"]:
            raise ValueError("研究记录校验失败；保留原数据，请检查备份，不将其作为学习证据")
        return dict(observation_id=row["request_id"], snapshot_sha256=row["sha256"], **json.loads(row["data"]))

    def capture(self, query):
        cost_query = CostQuery(**query.model_dump(exclude={"request_id"}))
        inputs = canonical(cost_query.model_dump())
        try:
            # An acknowledged retry returns its original historical snapshot,
            # even after expiry/restart, without fetching today's replacement.
            with closing(self._connect()) as db:
                if self._exists(db):
                    old = db.execute("SELECT * FROM event_research_observations WHERE request_id=?", (query.request_id,)).fetchone()
                    if old:
                        return self._existing(old, inputs)
            snapshot = self.details.cost(cost_query)
            now = self.clock()
            if (snapshot.get("market_id") != query.market_id or
                    snapshot.get("provider") != "polymarket" or snapshot.get("product") != "event" or
                    snapshot.get("simulation_ready") is not False or snapshot.get("execution_enabled") is not False or
                    snapshot.get("source_timestamp") is None or not 0 <= now-snapshot["source_timestamp"] < 30):
                raise ValueError("研究快照标识、权限或源时间无效，未保存")
            data = canonical(dict(schema_version=1, provider="polymarket", product="event", environment="research",
                kind="cost_observation", captured_at=now, inputs=cost_query.model_dump(), snapshot=snapshot,
                simulation_ready=False, execution_enabled=False))
            sha = digest(data)
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""CREATE TABLE IF NOT EXISTS event_research_observations(
                    request_id TEXT PRIMARY KEY, market_id TEXT NOT NULL, inputs TEXT NOT NULL,
                    captured_at REAL NOT NULL, data TEXT NOT NULL, sha256 TEXT NOT NULL)""")
                old = db.execute("SELECT * FROM event_research_observations WHERE request_id=?", (query.request_id,)).fetchone()
                if old:
                    return self._existing(old, inputs)
                db.execute("INSERT INTO event_research_observations VALUES(?,?,?,?,?,?)",
                    (query.request_id, query.market_id, inputs, now, data, sha))
            return dict(observation_id=query.request_id, snapshot_sha256=sha, **json.loads(data), duplicate=False)
        except sqlite3.Error:
            raise ValueError("研究记录暂不可用或数据库忙，请稍后重试；未变更交易状态") from None

    def _existing(self, row, inputs):
        if row["inputs"] != inputs:
            raise ValueError("同一保存请求不能改用其他参数，请重新计算后保存")
        return dict(self._decode(row), duplicate=True)

    def list(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("研究记录数量应为1至50")
        try:
            with closing(self._connect()) as db:
                if not self._exists(db):
                    return dict(rows=[], total=0, environment="research", execution_enabled=False)
                total = db.execute("SELECT COUNT(*) FROM event_research_observations").fetchone()[0]
                rows = db.execute("SELECT * FROM event_research_observations ORDER BY captured_at DESC,request_id DESC LIMIT ?", (limit,)).fetchall()
                return dict(rows=[self._decode(r) for r in rows], total=total, environment="research", execution_enabled=False)
        except sqlite3.Error:
            raise ValueError("研究记录暂不可用或数据库忙，请稍后重试") from None
