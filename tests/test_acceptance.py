import copy
import threading
import time
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import ccxt
import pytest
from execution import live
from execution.health import inspect_session, latest_report
from execution.venue import Venue
from terminal.config import Session
from terminal.runtime import Runtime


def wire_venue():
    v = Venue.__new__(Venue)
    v.name, v.env, v.swap = "okx", "live", False
    v.client = ccxt.okx({"apiKey": "fixture-key", "secret": "fixture-secret", "password": "fixture-pass",
                         "enableRateLimit": False})
    v.client.set_markets([dict(id="BTC-USDT", symbol="BTC/USDT", base="BTC", quote="USDT",
        baseId="BTC", quoteId="USDT", type="spot", spot=True, swap=False, future=False, option=False,
        contract=False, active=True, linear=False, inverse=False,
        precision={"amount": .000001, "price": .01},
        limits={"amount": {"min": .000001}, "price": {}, "cost": {}})])
    return v


def test_market_readiness_reports_actual_constraints():
    v = wire_venue()
    v.client.load_markets = Mock(return_value=v.client.markets)
    result = v.market_check()
    assert result["pairs"] == [dict(symbol="BTC/USDT", min_quantity=.000001,
        quantity_precision=.000001, price_precision=.01, precision_mode=ccxt.TICK_SIZE,
        min_notional=None)]
    v.client.load_markets.assert_called_once_with(True)


@pytest.mark.parametrize("field,value", [
    ("minimum", None), ("minimum", float("nan")), ("amount", 0),
    ("price", None), ("price", float("inf")), ("amount", True), ("cost", -1),
])
def test_market_readiness_rejects_incomplete_rules(field, value):
    v = wire_venue()
    v.client.load_markets = Mock(return_value=v.client.markets)
    m = v.client.market("BTC/USDT")
    if field == "minimum": m["limits"]["amount"]["min"] = value
    elif field == "cost": m["limits"]["cost"]["min"] = value
    else: m["precision"][field] = value
    with pytest.raises(ValueError, match="无法完成规则验收"):
        v.market_check()


def test_market_readiness_checks_all_active_candidates():
    v = wire_venue()
    good = copy.deepcopy(v.client.market("BTC/USDT"))
    bad = copy.deepcopy(good)
    bad.update(id="ETH-USDT", symbol="ETH/USDT", base="ETH", baseId="ETH")
    bad["precision"]["price"] = None
    v.client.set_markets([good, bad])
    v.client.load_markets = Mock(return_value=v.client.markets)
    with pytest.raises(ValueError, match="ETH/USDT"):
        v.market_check()


def test_market_readiness_handles_decimal_places_explicitly():
    v = wire_venue()
    v.client.load_markets = Mock(return_value=v.client.markets)
    v.client.precisionMode = ccxt.DECIMAL_PLACES
    v.client.market("BTC/USDT")["precision"] = {"amount": 0, "price": 2}
    assert v.market_check()["pairs"][0]["quantity_precision"] == 0
    v.client.market("BTC/USDT")["precision"]["price"] = .5
    with pytest.raises(ValueError, match="精度不完整"):
        v.market_check()


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("change", ["minimum_missing", "price_missing", "inactive", "minimum_increased"])
def test_order_rechecks_rules_after_successful_admission(side, change):
    v = wire_venue()
    v.client.load_markets = Mock(return_value=v.client.markets)
    assert v.market_check()["market_rules"] == "verified"
    changed = copy.deepcopy(v.client.market("BTC/USDT"))
    if change == "minimum_missing": changed["limits"]["amount"]["min"] = None
    if change == "price_missing": changed["precision"]["price"] = None
    if change == "inactive": changed["active"] = False
    if change == "minimum_increased": changed["limits"]["amount"]["min"] = 1
    def refresh(reload):
        assert reload is True
        v.client.set_markets([changed])
        return v.client.markets
    v.client.load_markets.side_effect = refresh
    v.quote = Mock(return_value=(100, 100.01, time.time()))
    v.balance = Mock(return_value=(1000, {"BTC": 1}))
    v.client.fetch_open_orders = Mock(return_value=[])
    v.client.create_order = Mock()
    with pytest.raises(ValueError):
        prepared = v.prepare("BTC", side, 20, .2, 100, 1)
        v.submit({"symbol": "BTC", "side": side, "client_id": "fixture"}, prepared)
    v.client.create_order.assert_not_called()
    if change != "minimum_increased":
        v.quote.assert_not_called()


def test_order_uses_refreshed_quantity_and_price_precision():
    v = wire_venue()
    changed = copy.deepcopy(v.client.market("BTC/USDT"))
    changed["precision"] = {"amount": .03, "price": .5}
    def refresh(reload):
        assert reload is True
        v.client.set_markets([changed])
        return v.client.markets
    v.client.load_markets = Mock(side_effect=refresh)
    v.quote = Mock(return_value=(100, 100.01, time.time()))
    v.balance = Mock(return_value=(1000, {"BTC": 1}))
    v.client.fetch_open_orders = Mock(return_value=[])
    prepared = v.prepare("BTC", "BUY", 20, 0, 100, 1)
    assert prepared["quantity"] == pytest.approx(.18)
    assert prepared["price"] == 100
    v.client.load_markets.assert_called_once_with(True)


def test_order_does_not_use_cached_rules_when_refresh_fails():
    v = wire_venue()
    v.client.load_markets = Mock(side_effect=ccxt.NetworkError("fixture timeout"))
    v.quote = Mock()
    v.client.create_order = Mock()
    with pytest.raises(ValueError, match="交易规则刷新失败，已阻止下单"):
        prepared = v.prepare("BTC", "BUY", 20, 0, 100, 1)
        v.submit({"symbol": "BTC", "side": "BUY", "client_id": "fixture"}, prepared)
    v.quote.assert_not_called()
    v.client.create_order.assert_not_called()


@pytest.mark.parametrize("field,rule", [
    ("amount", {"min": .1, "max": .01}),
    ("price", {"min": 2, "max": 1}),
    ("cost", {"min": 10, "max": 5}),
    ("amount", {"min": .000001, "max": float("nan")}),
    ("price", {"min": 0, "max": float("inf")}),
    ("cost", {"min": 0, "max": False}),
    ("amount", {"min": .000001, "max": 0}),
    ("price", {"min": -1, "max": 10}),
    ("cost", {"min": "1", "max": 10}),
    ("price", []),
])
def test_invalid_limit_ranges_block_admission_and_order(field, rule):
    v = wire_venue()
    v.client.market("BTC/USDT")["limits"][field] = rule
    v.client.load_markets = Mock(return_value=v.client.markets)
    v.quote = Mock()
    v.client.create_order = Mock()
    with pytest.raises(ValueError, match="无法完成规则验收"):
        v.market_check()
    with pytest.raises(ValueError, match="无法完成规则验收"):
        prepared = v.prepare("BTC", "BUY", 20, 0, 100, 1)
        v.submit({"symbol": "BTC", "side": "BUY", "client_id": "fixture"}, prepared)
    v.quote.assert_not_called()
    v.client.create_order.assert_not_called()


@pytest.mark.parametrize("field,high", [("amount", .1), ("price", 99), ("cost", 10)])
def test_valid_exchange_maximum_still_rejects_oversized_order(field, high):
    v = wire_venue()
    v.client.market("BTC/USDT")["limits"][field]["max"] = high
    v.client.load_markets = Mock(return_value=v.client.markets)
    assert v.market_check()["market_rules"] == "verified"
    v.quote = Mock(return_value=(100, 100.01, time.time()))
    v.balance = Mock(return_value=(1000, {"BTC": 1}))
    v.client.fetch_open_orders = Mock(return_value=[])
    v.client.create_order = Mock()
    with pytest.raises(ValueError, match="精度或金额规则"):
        prepared = v.prepare("BTC", "BUY", 20, 0, 100, 1)
        v.submit({"symbol": "BTC", "side": "BUY", "client_id": "fixture"}, prepared)
    v.client.create_order.assert_not_called()


def test_unspecified_optional_limits_are_not_invented():
    v = wire_venue()
    limits = v.client.market("BTC/USDT")["limits"]
    limits.pop("price"); limits.pop("cost")
    v.client.load_markets = Mock(return_value=v.client.markets)
    assert v.market_check()["pairs"][0]["min_notional"] is None
    v.quote = Mock(return_value=(100, 100.01, time.time()))
    v.balance = Mock(return_value=(1000, {"BTC": 1}))
    v.client.fetch_open_orders = Mock(return_value=[])
    assert v.prepare("BTC", "BUY", 20, 0, 100, 1)["quantity"] > 0


def row(i):
    return dict(billId=str(1000-i), tradeId=str(1000-i), ordId="123", instId="BTC-USDT",
                side="buy", fillSz="0.01", fillPx="100", fee="-0.00001", feeCcy="BTC",
                instType="SPOT", ts="1760000000000")


def test_signed_paginated_receipts_real_ccxt_parser():
    v, captured = wire_venue(), []
    pages = [[row(i) for i in range(100)], [row(100)]]
    def fetch(url, method, headers, body):
        assert method == "GET" and urlparse(url).path == "/api/v5/trade/fills-history"
        assert headers["OK-ACCESS-SIGN"] and body is None
        args = parse_qs(urlparse(url).query)
        assert args["instId"] == ["BTC-USDT"] and args["ordId"] == ["123"]
        captured.append(args)
        return {"code": "0", "data": pages.pop(0)}
    v.client.fetch = fetch
    fills = v.executions({"symbol":"BTC", "side":"BUY"}, {"id":"123"})
    assert len(fills) == 101 and captured[1]["after"] == ["901"]
    assert sum(t["amount"] for t in fills) == pytest.approx(1.01)
    assert fills[0]["fee"] == {"cost": .00001, "currency": "BTC"}


@pytest.mark.parametrize("bad", ["duplicate", "foreign", "fee", "identity", "error"])
def test_receipt_invalid_page_refuses_all(bad):
    v = wire_venue()
    first = [row(i) for i in range(100)]
    second = row(100)
    if bad == "duplicate": second["billId"] = first[-1]["billId"]
    if bad == "foreign": second["ordId"] = "foreign"
    if bad == "fee": second.pop("fee")
    if bad == "identity": second["instId"] = "ETH-USDT"
    pages = [{"code":"0","data":first}, {"code":"51000" if bad == "error" else "0","data":[second]}]
    v.client.fetch = lambda *a: pages.pop(0)
    with pytest.raises(ValueError):
        v.executions({"symbol":"BTC","side":"BUY"}, {"id":"123"})


def test_receipt_page_cap_is_not_silent_truncation():
    v, count = wire_venue(), 0
    def fetch(*args):
        nonlocal count
        data = [row(count*100+i) for i in range(100)]
        count += 1
        return {"code":"0","data":data}
    v.client.fetch = fetch
    with pytest.raises(ValueError, match="上限"):
        v.executions({"symbol":"BTC","side":"BUY"}, {"id":"123"})
    assert count == 20


@pytest.mark.parametrize("repeat", [False, True])
def test_algorithm_inventory_pages_and_all_types(repeat):
    v, requests = wire_venue(), []
    def fetch(url, method, headers, body):
        assert method == "GET" and headers["OK-ACCESS-SIGN"]
        assert urlparse(url).path == "/api/v5/trade/orders-algo-pending"
        p = parse_qs(urlparse(url).query); requests.append(p)
        rows = []
        if p["ordType"] == ["conditional"]:
            rows = [{"algoId":str(i), "instType":"SPOT", "instId":"BTC-USDT", "ordType":"conditional",
                     "state":"live","side":"sell","sz":"1","tdMode":"cash"} for i in range(100,200)]
            if "after" in p:
                assert p["after"] == ["199"]
                rows = rows[-1:] if repeat else []
        return {"code":"0","data":rows}
    v.client.fetch = fetch
    if repeat:
        with pytest.raises(ValueError,match="分页重复"): v.algo_inventory()
    else:
        assert len(v.algo_inventory()) == 100
        assert len(requests) == 8
        assert {p["ordType"][0] for p in requests} == {
            "conditional","oco","trigger","move_order_stop","iceberg","twap","smart_iceberg"}


def remote(rt):
    rt.vault.update("okx/live", {"key":"fixture"})
    with rt.db.db:
        return rt.new(Session(consent=True,execution="live", source="public",confirmation="启用实盘"))


def health_venue(rt):
    v = Mock()
    v.name = "okx"
    v.permission_check.return_value = {"venue_account_id":"fixture-hash"}
    v.market_check.return_value = {"market_rules":"verified"}
    v.audit.return_value = {"dedicated_balance_match":True,"checked":int(time.time())}
    v.algo_inventory.return_value = []
    v.quote.return_value = (100,100.01,time.time())
    rt.venue = lambda c:v
    return v


def test_health_is_read_only_and_report_survives_restart(tmp_path):
    rt=Runtime(tmp_path); s=remote(rt); v=health_venue(rt)
    before=copy.deepcopy(rt.db.load())
    report=inspect_session(rt,s["id"])
    assert report["status"] == "READ_ONLY_PASSED"
    assert not report["authorizes_trading"] and not report["real_funds_verified"]
    assert rt.db.load() == before
    assert not list(rt.db.db.execute("select * from venue_orders"))
    v.submit.assert_not_called()
    v.client.create_order.assert_not_called()
    rt.db.db.close()
    rt=Runtime(tmp_path)
    restored = latest_report(rt,s["id"])
    assert restored["requires_recheck"] and any("重启" in r for r in restored["recheck_reasons"])
    assert restored["checks"] == report["checks"] and not restored["authorizes_trading"]
    assert rt.db.load()["lifecycle_status"] == "CREATED"
    rt.db.db.close()


@pytest.mark.parametrize("failure", ["algo","balance","unknown","changed","account"])
def test_health_blocks_invalid_evidence(tmp_path, failure):
    rt=Runtime(tmp_path); s=remote(rt); v=health_venue(rt)
    if failure == "algo": v.algo_inventory.return_value = [{"algoId":"external"}]
    if failure == "balance": v.audit.side_effect = ValueError("专用账户余额不符")
    if failure == "account":
        with rt.db.db:
            s["venue_account_id"]="different"; rt.db.save(s)
    if failure == "unknown":
        with rt.db.db:
            live.enqueue(rt.db,s,"BTC","BUY",{"price":100,"time":int(time.time())},10,"fixture")
            live.save(rt.db,live.pending(rt.db,s["id"]),"UNKNOWN")
    if failure == "changed":
        def change(_):
            with rt.lock,rt.db.db:
                state=rt.db.load(); state["config"]["capital"] += 1; rt.db.save(state)
            return {}
        v.audit.side_effect=change
    report=inspect_session(rt,s["id"])
    assert report["status"] == "BLOCKED" and not report["authorizes_trading"]
    assert not rt.db.load().get("admitted")
    v.submit.assert_not_called()
    rt.db.db.close()


def test_health_network_never_holds_database_lock(tmp_path):
    rt=Runtime(tmp_path); s=remote(rt); v=health_venue(rt)
    entered,release=threading.Event(),threading.Event()
    def slow():
        entered.set(); assert release.wait(3); return {"market_rules":"verified"}
    v.market_check.side_effect=slow
    result=[]
    t=threading.Thread(target=lambda:result.append(inspect_session(rt,s["id"])))
    t.start(); assert entered.wait(1)
    try:
        assert rt.lock.acquire(timeout=.5)
        rt.lock.release()
        with pytest.raises(ValueError,match="正在进行"): inspect_session(rt,s["id"])
    finally:
        release.set(); t.join(3)
    assert result and result[0]["status"] == "READ_ONLY_PASSED"
    rt.db.db.close()


def test_paper_cannot_be_used_as_live_acceptance(tmp_path):
    rt=Runtime(tmp_path)
    with rt.db.db: s=rt.new(Session(consent=True))
    with pytest.raises(ValueError,match="不能作为实盘验收"): inspect_session(rt,s["id"])
    assert not rt.db.db.execute("SELECT * FROM acceptance_reports").fetchone()
    rt.db.db.close()
