import time
from unittest.mock import Mock, patch
import pytest
from ai.provider import Advice
from terminal.runtime import Runtime
from terminal.config import Session
from execution import live
from execution.venue import Venue
from market.feeds import historical, START
from market.imports import parse_csv, window
from challenge.manager import scan, finish
from strategy.rules import analyze
from risk.limits import equity


@pytest.fixture
def rt(tmp_path):
    rt = Runtime(tmp_path)
    yield rt
    rt.db.db.close()


@pytest.mark.parametrize("profile", ["normal", "challenge"])
def test_full_day(rt, profile):
    with patch("socket.socket", side_effect=AssertionError("offline")), rt.db.db:
        s = rt.new(
            Session(
                profile=profile,
                consent=True,
                settlement="close",
                loss_limit=90,
                breaker=50,
            )
        )
        rt.command(s["id"], "start")
        s = rt.db.load()
        for minute in range(1441):
            t = START + minute * 60
            scan(rt.db, s, t, historical(t), manage=minute < 1440)
        finish(rt.db, s)
        r = rt.db.entries("reports", s["id"])[0]["data"]
        assert r["fills"] > 0 and not s["positions"] and r["fees"] > 0
        assert abs(equity(s) - s["config"]["capital"] - s["realized"]) < 1e-7
        print(profile, r["fills"], r["nav"], r["max_drawdown"])


@pytest.mark.parametrize("profile", ["normal", "challenge"])
@pytest.mark.parametrize("failed", [False, True])
def test_ai(rt, profile, failed):
    if profile == "challenge":
        with pytest.raises(ValueError, match="规则引擎"):
            Session(profile=profile, engine="ai", consent=True)
        with rt.db.db:
            rt.new(Session(profile=profile, consent=True))
            rt.command(rt.db.load()["id"], "start")
        with patch("terminal.runtime.Provider.propose", side_effect=AssertionError("规则挑战调用了模型")):
            rt.tick()
        assert rt.db.load()["radar"] and not rt.db.load().get("ai_calls")
        return
    with rt.db.db:
        rt.vault.update("ai_key", "test-key")
        rt.vault.update(
            "ai_config",
            dict(model="mock", base="https://invalid.test/v1", fallback="rules"),
        )
        s = rt.new(Session(profile=profile, engine="ai", consent=True))
        rt.command(s["id"], "start")
    prop = Advice(
        symbol="BTC",
        action="BUY",
        fraction=0.06,
        reason="测试样本",
        risk="回撤",
        exit_plan="按止损退出",
    )
    with patch(
        "terminal.runtime.Provider.propose",
        side_effect=ValueError("bad") if failed else None,
        return_value=("市场摘要", prop),
    ):
        rt.tick()
        assert rt.ai.worker.flight.done.wait(2)
        rt.tick()
    s = rt.db.load()
    assert s["ai_calls"] == 2 and s["ai_failed"] == failed
    assert rt.db.entries("system_events", s["id"], kind="AI_ERROR" if failed else "AI")
    if not failed:
        assert "BTC" in s["paper_pending"] and not s["positions"]
        with rt.db.db:
            scan(rt.db, s, START + 60, historical(START + 60))
        assert "BTC" in s["positions"] and s["positions"]["BTC"]["cost"] < 61
    assert (
        b"test-key" not in rt.vault.path.read_bytes()
        and "ai_key" not in rt.vault.public()
    )


@pytest.mark.parametrize("name", ["okx", "binance"])
@pytest.mark.parametrize("product", ["spot", "swap"])
@pytest.mark.parametrize("env", ["demo", "live"])
def test_execution_recovery(rt, name, product, env):
    # Test double for transport only. Real outbox, application lifecycle and accounting.
    venue = Mock()
    venue.prepare.return_value = {"quantity": 2, "price": 10, "contract": 1, "quote_time":time.time()}
    venue.preflight.return_value = {"venue_account_id":"mock", "dedicated_balance_match":True, "checked":time.time()}
    venue.audit.return_value = {"dedicated_balance_match":True}
    venue.submit.side_effect = TimeoutError()
    venue.lookup.return_value = dict(id="e1", status="canceled", filled=1)
    venue.executions.return_value = [
        dict(
            id="trade1",
            order="e1",
            amount=1,
            price=10,
            side="buy",
            fees=[dict(currency="USDT", cost=0.01)],
        )
    ]
    rt.venue = lambda c: venue
    with rt.db.db:
        rt.vault.update(name + "/" + env, {"key": "fixture"})
        legacy = product == "swap" and env == "live"
        if legacy:
            with pytest.raises(ValueError, match="仅支持现货"):
                rt.new(Session(consent=True, product=product, execution=env, source="public", confirmation="启用实盘"))
        s = rt.new(
            Session(
                profile="challenge",
                execution=env,
                exchange=name,
                product="spot" if legacy else product,
                source="public",
                confirmation="启用实盘",
                consent=True,
            )
        )
        rt.command(s["id"], "start", "启用实盘")
        s = rt.db.load()
        s["lifecycle_status"] = "RUNNING"
        rt.db.save(s)
        live.enqueue(
            rt.db, s, "BTC", "BUY", {"price": 10, "time": int(time.time())}, 20, "test"
        )
        if legacy:
            # Simulate an already transmitted historical swap. Recovery may
            # query it, but must not call create_order for the obsolete product.
            s["config"]["product"] = product
            rt.db.save(s)
            old = live.pending(rt.db, s["id"])
            old.update(product=product, prepared=venue.prepare.return_value)
            live.save(rt.db, old, "UNKNOWN")
    if not legacy:
        rt.tick()
    o = live.pending(rt.db, s["id"])
    assert o["stage"] == "UNKNOWN" and not rt.db.entries("fills", s["id"])
    with rt.db.db:
        rt.command(s["id"], "stop")
        o["retry"] = 0
        live.save(rt.db, o, "UNKNOWN")
    rt.tick()
    s = rt.db.load()
    assert s["lifecycle_status"] == "STOPPED" and s["positions"]["BTC"]["qty"] == 1
    assert venue.submit.call_count == (0 if legacy else 1) and len(rt.db.entries("fills", s["id"])) == 1
    assert (
        rt.db.db.execute("SELECT stage FROM venue_orders").fetchone()[0]
        == "PARTIAL_CANCELLED"
    )
    assert not live.pending(rt.db, s["id"])
    assert abs(s["cash"] - (s["config"]["capital"] - 10.01)) < 1e-8


@pytest.mark.parametrize("venue_name", ["okx", "binance"])
@pytest.mark.parametrize("swap", [False, True])
def test_transport_order_arguments(venue_name, swap):
    v = Venue.__new__(Venue)
    v.name = venue_name
    v.swap = swap
    v.client = Mock()
    v.submit(
        {"client_id": "sm0001", "symbol": "BTC", "side": "SELL"},
        {"quantity": 1, "price": 100},
    )
    a = v.client.create_order.call_args.args
    assert a[0] == ("BTC/USDT:USDT" if swap else "BTC/USDT")
    assert a[1:5] == ("limit", "sell", 1, 100) and a[5]["timeInForce"] == "IOC"
    assert bool(a[5].get("reduceOnly")) == swap


def test_csv(rt):
    bars = historical(START)["BTC"]
    text = "symbol,timestamp,open,high,low,close,quote_volume\n" + "\n".join(
        "BTC," + ",".join(map(str, b)) for b in bars
    )
    with rt.db.db:
        key = rt.add_csv("test.csv", text)
        s = rt.new(Session(source="csv", dataset=key, consent=True))
        rt.command(s["id"], "start")
    rt.tick()
    s = rt.db.load()
    assert s["radar"] and s["radar"][0]["time"] == s["t"]
    assert max(b[0] for b in rt.feed(s["config"], s["t"])["BTC"]) <= s["t"]
    with pytest.raises(ValueError):
        parse_csv(text + "\n" + text.splitlines()[-1])
    with rt.db.db:
        rt.command(s["id"], "pause")
        rt.command(s["id"], "step")
    assert rt.db.load()["t"] == s["t"] + 60


def test_live_guards(rt):
    with pytest.raises(ValueError):
        Session(execution="live", source="history", consent=True)
    with pytest.raises(ValueError):
        Session(execution="live", source="public", consent=True)
    with pytest.raises(ValueError):
        rt.new(
            Session(
                execution="live", source="public", consent=True, confirmation="启用实盘"
            )
        )
    with pytest.raises(ValueError):
        Advice(
            symbol="BTC",
            action="BUY",
            fraction=1.1,
            reason="bad",
            risk="a",
            exit_plan="b",
        )


def test_original_acceptance():
    from integration import run

    run()
