import json
import sqlite3


def encode(v):
    return json.dumps(v, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


TABLES = (
    "market_snapshots",
    "decisions",
    "risk_checks",
    "simulated_orders",
    "fills",
    "portfolio_snapshots",
    "system_events",
    "reports",
)


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS paper_signal_keys(signal_id TEXT PRIMARY KEY,challenge_id INTEGER NOT NULL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS challenges(id INTEGER PRIMARY KEY,state TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS challenge_configs(challenge_id INTEGER PRIMARY KEY REFERENCES challenges, config TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS positions(challenge_id INTEGER REFERENCES challenges, symbol TEXT, data TEXT, PRIMARY KEY(challenge_id,symbol))"
        )
        for table in TABLES:
            self.db.execute(
                f"CREATE TABLE IF NOT EXISTS {table}(id INTEGER PRIMARY KEY,challenge_id INTEGER REFERENCES challenges,t INTEGER,symbol TEXT,kind TEXT,summary TEXT,data TEXT)"
            )
            self.db.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{table} ON {table}(challenge_id,id)"
            )
        self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS unique_fill ON fills(challenge_id,t,symbol,kind)"
        )

    def record(self, table, s, kind, summary="", symbol="", data=None):
        return self.db.execute(
            f"INSERT INTO {table}(challenge_id,t,symbol,kind,summary,data) VALUES(?,?,?,?,?,?)",
            (s["id"], s["t"], symbol, kind, summary, encode(data or {})),
        ).lastrowid

    def entries(self, table, cid, limit=-1, offset=0, symbol="", kind=""):
        where = "challenge_id=?"
        params = [cid]
        for key, value in [("symbol", symbol), ("kind", kind)]:
            if value:
                where += f" AND {key}=?"
                params.append(value)
        rows = self.db.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        return [dict(dict(r), data=json.loads(r["data"])) for r in rows]

    def load(self, cid=None):
        r = self.db.execute(
            "SELECT state FROM challenges "
            + ("WHERE id=?" if cid else "ORDER BY id DESC LIMIT 1"),
            (cid,) if cid else (),
        ).fetchone()
        return json.loads(r[0]) if r else None

    def save(self, s):
        self.db.execute(
            "UPDATE challenges SET state=? WHERE id=?", (encode(s), s["id"])
        )
