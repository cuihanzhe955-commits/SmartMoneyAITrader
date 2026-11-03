import time
import pytest
from terminal.config import Session
from terminal.runtime import Runtime
from execution.venue import Venue
from execution.live import enqueue, pending
from market.feeds import START, historical
from challenge.manager import scan, action
from market.imports import window


def test_restricted_data_pauses(tmp_path):
    rt = Runtime(tmp_path)
    try:
        with rt.db.db:
            s = rt.new(Session(consent=True, source="public", exchange="binance"))
            rt.command(s["id"], "start")

        def restricted(*args):
            raise RuntimeError("HTTP 451 restricted location")

        rt.feed = restricted
        rt.tick()
        s = rt.db.load()
        assert (
            s["lifecycle_status"] == "PAUSED"
            and "451" in s["latest"]
            and not rt.db.entries("fills", s["id"])
        )
    finally:
        rt.db.db.close()


def test_resume_after_interruption(tmp_path):
    rt = Runtime(tmp_path)
    with rt.db.db:
        rt.vault.update("okx/live", {"key": "fixture"})
        s = rt.new(
            Session(
                consent=True, execution="live", source="public", confirmation="启用实盘"
            )
        )
        rt.command(s["id"], "start", "启用实盘")
        s = rt.db.load()
        s["lifecycle_status"] = "RUNNING"
        rt.db.save(s)
        enqueue(
            rt.db, s, "BTC", "BUY", {"time": int(time.time()), "price": 100}, 10, "test"
        )
    rt.db.db.close()
    rt = Runtime(tmp_path)
    rt.start_worker()
    rt.exit.set()
    rt.thread.join()
    try:
        assert (
            rt.db.load()["lifecycle_status"] == "PAUSED"
            and pending(rt.db, s["id"]) is None
        )
        assert (
            rt.db.db.execute("select stage from venue_orders").fetchone()[0]
            == "CANCELLED"
        )
    finally:
        rt.db.db.close()


def test_strict_min_and_delay(tmp_path):
    rt = Runtime(tmp_path)
    try:
        with rt.db.db:
            s = rt.new(
                Session(
                    profile="challenge", paper_rules="venue", consent=True, capital=10
                )
            )
            assert "BTC" in s["config"]["precision_rules"]
            for i in range(160):
                t = START + i * 60
                scan(rt.db, s, t, historical(t))
            orders = rt.db.entries("simulated_orders", s["id"])
            assert any(o["kind"] == "FILLED" for o in orders)
            assert any(o["kind"] == "CANCELLED" for o in orders)
            fills = rt.db.entries("fills", s["id"])
            for f in fills:
                order = next(o for o in orders if o["id"] == f["data"]["order_id"])
                assert f["t"] >= order["t"] + 60
    finally:
        rt.db.db.close()
