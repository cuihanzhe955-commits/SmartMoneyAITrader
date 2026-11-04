import json
import time
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest

from execution.hosted import HostedStops
from execution.stop_transport import DemoStops
from test_acceptance import wire_venue
from test_hosted import state, detail, ack


@pytest.fixture
def service(tmp_path):
    ledger = HostedStops(tmp_path / "ledger.db")
    v = wire_venue()
    v.env = "demo"
    v.client.set_sandbox_mode(True)
    s = state()
    s.update(admitted=True, venue_account_id="demo-uid")
    v.permission_check = Mock(return_value={"venue_account_id": "demo-uid"})
    v.audit_spot = Mock(return_value={"dedicated_balance_match": True})
    v.algo_inventory = Mock(return_value=[])
    v.quote = Mock(side_effect=lambda symbol: (100, 101, time.time()))
    v.client.load_markets = Mock(return_value=v.client.markets)
    order = ledger.plan(s, "BTC", 90)
    calls = []
    query = detail(order)
    def fetch(url, method, headers, body):
        path = urlparse(url).path
        # CCXT fetch merges client default headers after this interception point.
        effective_headers = {**v.client.headers, **headers}
        assert effective_headers["x-simulated-trading"] == "1" and headers["OK-ACCESS-SIGN"]
        if method == "POST":
            stage = ledger.get(order["client_id"])["stage"]
            assert stage == ("CANCEL_PENDING" if path.endswith("cancel-algos") else "SENDING")
        calls.append((path, method, json.loads(body) if body else None))
        return {"code": "0", "data": [query.copy()]} if method == "GET" else ack(order)
    v.client.fetch = fetch
    try:
        yield DemoStops(ledger, v, lambda: s), order, s, calls, query
    finally:
        ledger.close()


def test_demo_create_query_cancel_confirm_signed_protocol(service):
    svc, order, state, calls, query = service
    cid = order["client_id"]
    assert svc.create(cid)["stage"] == "ACCEPTED"
    assert calls[0] == ("/api/v5/trade/order-algo", "POST", dict(
        instId="BTC-USDT", tdMode="cash", side="sell", ordType="conditional", sz="0.1",
        slTriggerPx="90", slOrdPx="-1", slTriggerPxType="last", algoClOrdId=cid, tgtCcy="base_ccy"))
    assert svc.reconcile(cid)["stage"] == "LIVE"
    assert svc.cancel(cid)["stage"] == "CANCEL_PENDING"
    assert calls[-1] == ("/api/v5/trade/cancel-algos", "POST", [{"algoId": "algo1", "instId": "BTC-USDT"}])
    assert svc.ledger.exit_blocked(cid)
    query.update(state="canceled", uTime="1001")
    assert svc.reconcile(cid)["stage"] == "CANCELED"
    assert not svc.ledger.exit_blocked(cid)


@pytest.mark.parametrize("problem", ["live", "header", "sandbox", "uid", "admission", "quantity", "precision", "cost", "stale", "external", "balance"])
def test_preflight_failure_sends_no_order(service, problem):
    svc, o, s, calls, _ = service
    v = svc.venue
    if problem == "live": v.env = "live"
    elif problem == "header": v.client.headers.clear()
    elif problem == "sandbox": v.client.options["sandboxMode"] = False
    elif problem == "uid": s["venue_account_id"] = "wrong"
    elif problem == "admission": s["admitted"] = False
    elif problem == "quantity": s["positions"]["BTC"]["qty"] = .05
    elif problem == "precision": v.client.market("BTC/USDT")["precision"]["amount"] = .3
    elif problem == "cost": v.client.market("BTC/USDT")["limits"]["cost"]["min"] = 100
    elif problem == "stale": v.quote.side_effect = lambda symbol: (100,101,time.time()-60)
    elif problem == "external": v.algo_inventory.return_value = [{"algoId": "external"}]
    elif problem == "balance": v.audit_spot.return_value = {"dedicated_balance_match": False}
    with pytest.raises(Exception):
        svc.create(o["client_id"])
    assert not calls and svc.ledger.get(o["client_id"])["stage"] == "PLANNED"


def test_late_position_change_stops_send(service):
    svc, o, s, calls, _ = service
    def quote(symbol):
        s["positions"]["BTC"]["opening_order"] = "replacement"
        return 100, 101, time.time()
    svc.venue.quote.side_effect = quote
    with pytest.raises(ValueError, match="持仓已变化"):
        svc.create(o["client_id"])
    assert not calls


def test_late_authorization_change_stops_send(service):
    svc, o, s, calls, _ = service
    def quote(symbol):
        s["admitted"] = False
        return 100, 101, time.time()
    svc.venue.quote.side_effect = quote
    with pytest.raises(ValueError, match="发送前授权"):
        svc.create(o["client_id"])
    assert not calls


def test_submit_timeout_is_durable_and_recovery_only_queries(service):
    svc, o, _, calls, query = service
    original = svc.venue.client.fetch
    def timed_out(url, method, headers, body):
        result = original(url,method,headers,body)
        if method == "POST": raise TimeoutError("private-response-not-for-ui")
        return result
    svc.venue.client.fetch = timed_out
    cid = o["client_id"]
    with pytest.raises(ValueError, match="提交结果未确认") as exc:
        svc.create(cid)
    assert "private-response" not in str(exc.value)
    assert svc.ledger.get(cid)["stage"] == "UNKNOWN"
    with pytest.raises(ValueError, match="禁止重复"):
        svc.create(cid)
    assert svc.reconcile(cid)["stage"] == "LIVE"
    assert sum(method == "POST" for _,method,_ in calls) == 1


def test_cancel_timeout_and_trigger_race_never_repeats_cancel(service):
    svc,o,_,calls,query = service
    cid=o["client_id"]
    svc.create(cid)
    original=svc.venue.client.fetch
    def timeout(url,method,headers,body):
        result=original(url,method,headers,body)
        if urlparse(url).path.endswith("cancel-algos"): raise TimeoutError()
        return result
    svc.venue.client.fetch=timeout
    with pytest.raises(ValueError, match="撤销结果未确认"): svc.cancel(cid)
    with pytest.raises(ValueError): svc.cancel(cid)
    query.update(state="effective",ordIdList=["child1"],actualSz="0.1",uTime="1002")
    assert svc.reconcile(cid)["stage"]=="TRIGGERED"
    with pytest.raises(ValueError): svc.cancel(cid)
    assert len([p for p,m,b in calls if p.endswith("cancel-algos")])==1
    assert svc.ledger.exit_blocked(cid)
