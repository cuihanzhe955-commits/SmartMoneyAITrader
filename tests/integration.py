"""Offline acceptance run, including a full UTC market day. No external sockets allowed."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from challenge.manager import *
from events.store import Store
from market.feeds import SYMBOLS
from execution.broker import fill
from risk.limits import equity


def run():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "socket.socket", side_effect=AssertionError("network disabled")
    ):
        path = Path(tmp) / "test.db"
        db = Store(path)
        with db.db:
            s = create(db, dict(consent=True, settlement="close"))
            action(db, s, "start")
        peak_slots = 0
        for i in range(1441):
            with db.db:
                scan(db, s, START + 60 * i, manage=i < 1440)
                assert s["cash"] >= 0 and s["lifecycle_status"] == "RUNNING"
                peak_slots = max(peak_slots, len(s["positions"]))
                if i == 1440:
                    finish(db, s)
            if i == 720:
                old = db.entries("fills", s["id"], 1)
                db.db.close()
                db = Store(path)
                s = db.load()
                assert (
                    s["t"] == START + 720 * 60
                    and db.entries("fills", s["id"], 1) == old
                )
        r = db.entries("reports", 1, 1)[0]["data"]
        print(
            "24H",
            {
                k: r[k]
                for k in (
                    "fills",
                    "nav",
                    "return_pct",
                    "max_drawdown",
                    "fees",
                    "slippage",
                    "rejections",
                )
            },
            "peak_slots",
            peak_slots,
            flush=True,
        )
        assert (
            r["end"] - r["start"] == 86400
            and r["fills"] > 0
            and peak_slots > 1
            and r["fees"] > 0
            and r["slippage"] > 0
        )
        assert not s["positions"] and abs(s["cash"] - s["realized"] - 10) < 1e-9
        kinds = {r[0] for r in db.db.execute("select distinct kind from decisions")}
        assert {"BUY", "SELL", "HOLD", "REJECT"} <= kinds
        assert len(s["radar"]) == len(SYMBOLS)
        with db.db:
            a = create(db, {"consent": True})
            action(db, a, "start")
            scan(db, a, START)
            action(db, a, "pause")
            before = db.entries("fills", 2)
            action(db, a, "resume")
            scan(db, a, START, {}, True)
            assert (
                a["lifecycle_status"] == "DATA_STALE"
                and db.entries("fills", 2) == before
            )
            action(db, a, "resume")
            scan(db, a, START + 60, manage=False)
            assert a["lifecycle_status"] == "RUNNING"
            action(db, a, "stop")
            assert a["lifecycle_status"] == "STOPPED"
        # Isolated, labeled test fixtures exercise exact exit boundaries.
        for mode in ("固定止损", "移动止损", "熔断"):
            with db.db:
                a = create(
                    db, {"consent": True, "breaker": 5 if mode == "熔断" else 35}
                )
                action(db, a, "start")
                rows = historical(START)
                k = "SOL"
                m = analyze(rows[k], START, a["config"])
                price = m["price"]
                entry = price * (
                    1.5 if mode == "熔断" else 1.04 if mode == "固定止损" else 1
                )
                fill(db, a, k, "BUY", dict(m, price=entry), 5, "test fixture")
                if mode == "移动止损":
                    a["positions"][k]["high"] = price * 1.05
                scan(db, a, START, rows)
                if mode == "熔断":
                    assert a["breaker"] and a["lifecycle_status"] == "PAUSED"
                else:
                    assert any(
                        r["summary"] == mode
                        for r in db.entries("fills", a["id"], kind="SELL")
                    )
                action(db, a, "stop")
        with db.db:
            a = create(db, {"consent": True, "settlement": "close"})
            action(db, a, "start")
            scan(db, a, START, manage=False)
            m = a["radar"][0]
            fill(db, a, m["symbol"], "BUY", m, 2, "disconnect fixture")
            scan(db, a, START + 1, {})
            finish(db, a)
            assert a["pending"] and a["positions"]
            assert not db.entries("fills", a["id"], kind="SELL")
        assert db.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        db.db.close()
        print(
            "PASS offline full replay, ledger, restart, stale, pause, resume, exits, breaker and isolation",
            flush=True,
        )


if __name__ == "__main__":
    run()
