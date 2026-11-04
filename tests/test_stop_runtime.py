import time
from unittest.mock import Mock, patch

import pytest

from execution import live
from execution.hosted import HostedStops
from terminal.runtime import Runtime
from terminal.config import Session
from test_acceptance import wire_venue
from test_hosted import detail


@pytest.fixture
def active(tmp_path):
    rt = Runtime(tmp_path)
    rt.vault.update("okx/demo", {"key":"fixture", "secret":"fixture", "passphrase":"fixture"})
    with rt.db.db:
        s = rt.new(Session(consent=True))
        s["config"].update(exchange="okx",execution="demo",product="spot")
        s.update(account_ref=rt.account_ref(s["config"]),venue_account_id="fixture-uid",cash=90)
        s["positions"]["BTC"] = dict(qty=.1,cost=10,price=100,high=100,entry=100,opened=s["t"],opening_order="entry1")
        rt.db.save(s)
    ledger = HostedStops(tmp_path/"terminal.db")
    o = ledger.plan(s,"BTC",90);ledger.begin_create(o["client_id"],s)
    v=wire_venue();v.env="demo";v.client.set_sandbox_mode(True)
    v.permission_check=Mock(return_value={"venue_account_id":"fixture-uid"})
    v.lookup_stop=Mock(return_value=detail(o))
    v.client.create_order=Mock();v.client.cancel_order=Mock()
    rt.venue=lambda c:v
    try:yield rt,ledger,o,v
    finally:
        rt.shutdown();ledger.close();rt.db.db.close()


def test_runtime_recovers_original_demo_order_and_exposes_status(active):
    rt,ledger,o,v=active
    rt.hosted_tick()
    assert ledger.get(o["client_id"])["stage"]=="LIVE"
    status=rt.hosted_status()
    assert status["blocks_orders"] and not status["automatic_creation"]
    assert status["orders"][0]["stage"]=="LIVE"
    assert "scope" not in status["orders"][0]
    v.client.create_order.assert_not_called();v.client.cancel_order.assert_not_called()


def test_changed_credentials_stop_recovery_without_query(active):
    rt,ledger,o,v=active
    rt.vault.update("okx/demo",{"key":"changed"})
    rt.hosted_tick()
    assert ledger.get(o["client_id"])["maintenance_error"]
    v.lookup_stop.assert_not_called()


def test_hosted_recovery_uses_same_order_mutex(active):
    rt,ledger,o,v=active
    rt.order_mutex.acquire()
    try:rt.hosted_tick()
    finally:rt.order_mutex.release()
    v.lookup_stop.assert_not_called()


@pytest.mark.parametrize("side",["BUY","SELL"])
def test_hosted_blocks_all_ordinary_order_intents(active,side):
    rt,ledger,o,v=active
    with rt.db.db:
        s=rt.db.load()
        live.enqueue(rt.db,s,"BTC",side,{"price":100,"time":int(time.time())},10,"fixture")
    assert not live.pending(rt.db,s["id"])
    assert "保护单" in rt.db.entries("system_events",s["id"],kind="REJECT")[0]["summary"]
    with pytest.raises(ValueError,match="托管保护单"):
        rt.valid_intent(s,{})
    with pytest.raises(ValueError,match="托管保护单"):
        rt.new(Session(consent=True))


def test_runtime_triggered_partial_fill_only_processed_by_hosted_lane(active):
    rt,ledger,o,v=active
    v.lookup_stop.return_value=detail(o,state="effective",ordIdList=["child1"],actualSz=".1")
    v.client.fetch_order=Mock(return_value=dict(id="child1",symbol="BTC/USDT",side="sell",amount=.1,filled=.04,status="open"))
    v.executions=Mock(return_value=[dict(id="fill1",order="child1",symbol="BTC/USDT",side="sell",amount=.04,price=90,fee=dict(currency="USDT",cost=.0036))])
    rt.hosted_tick()
    assert rt.db.load()["positions"]["BTC"]["qty"]==pytest.approx(.06)
    before=rt.db.load()
    rt.dispatch=Mock()
    rt.order_tick()
    rt.dispatch.assert_not_called()
    assert rt.db.load()==before


def test_worker_lifecycle_has_hosted_lane_and_empty_database_stays_lazy(tmp_path):
    rt=Runtime(tmp_path)
    try:
        with patch.object(rt,"loop"):
            rt.start_worker()
        assert any(t.name=="smart-money-hosted" for t in rt.threads)
        rt.hosted_tick()
        assert rt.hosted_ledger is None
        assert not rt.hosted_status()["orders"]
    finally:rt.shutdown();rt.db.db.close()
