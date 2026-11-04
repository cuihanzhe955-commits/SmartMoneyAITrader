from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from execution.hosted import HostedStops
from terminal.runtime import Runtime
from test_stop_transport import service
from test_stop_runtime import active
from test_stop_settlement import triggered, receipts
from test_stop_release import release_service


def test_cancel_retries_require_fresh_query_cooldown_and_cap(service):
    svc,o,_,calls,query=service
    cid=o["client_id"];svc.create(cid)
    with patch("execution.hosted.time.time",return_value=100):
        assert svc.cancel(cid)["cancel_attempts"]==1
        with pytest.raises(ValueError,match="尚未到重试时间"):svc.cancel(cid)
    with patch("execution.hosted.time.time",return_value=131):
        assert svc.cancel(cid)["cancel_attempts"]==2
    with patch("execution.hosted.time.time",return_value=192):
        assert svc.cancel(cid)["cancel_attempts"]==3
    with patch("execution.hosted.time.time",return_value=400):
        with pytest.raises(ValueError,match="三次上限"):svc.cancel(cid)
    assert len([p for p,m,b in calls if p.endswith("cancel-algos")])==3
    assert len([p for p,m,b in calls if p.endswith("order-algo") and m=="POST"])==1


def test_cancel_timeout_budget_survives_connection_restart(service):
    svc,o,_,calls,query=service;cid=o["client_id"];svc.create(cid)
    original=svc.venue.client.fetch
    def timeout(url,method,headers,body):
        result=original(url,method,headers,body)
        if "cancel-algos" in url:raise TimeoutError()
        return result
    svc.venue.client.fetch=timeout
    with patch("execution.hosted.time.time",return_value=100):
        with pytest.raises(ValueError,match="撤销结果未确认"):svc.cancel(cid)
    path=svc.ledger.db.execute("PRAGMA database_list").fetchone()[2]
    reopened=HostedStops(path);first=svc.ledger;svc.ledger=reopened
    try:
        with patch("execution.hosted.time.time",return_value=110):
            with pytest.raises(ValueError,match="尚未到重试时间"):svc.cancel(cid)
        assert reopened.get(cid)["cancel_attempts"]==1
        assert len([p for p,m,b in calls if p.endswith("cancel-algos")])==1
    finally:svc.ledger=first;reopened.close()


def test_trigger_during_cooldown_cannot_submit_another_cancel(service):
    svc,o,_,calls,query=service;cid=o["client_id"];svc.create(cid)
    with patch("execution.hosted.time.time",return_value=100):svc.cancel(cid)
    query.update(state="effective",uTime="1001",ordIdList=["child1"],actualSz=".1")
    with patch("execution.hosted.time.time",return_value=200):
        with pytest.raises(ValueError):svc.cancel(cid)
    assert svc.ledger.get(cid)["stage"]=="TRIGGERED"
    assert len([p for p,m,b in calls if p.endswith("cancel-algos")])==1


@pytest.mark.parametrize("age,stale",[(0,False),(14,False),(16,True),(-1,True)])
def test_ui_marks_old_or_future_protection_observation(active,age,stale):
    rt,ledger,o,v=active;rt.hosted_tick()
    saved=ledger.get(o["client_id"])
    with patch("terminal.runtime.time.time",return_value=saved["last_query_at"]+age):
        row=rt.hosted_status()["orders"][0]
    assert row["stale"] is stale
    assert row["needs_attention"] is stale


@pytest.mark.parametrize("field",["key","secret","passphrase"])
def test_saving_credentials_rebuilds_cached_client(tmp_path,field):
    rt=Runtime(tmp_path)
    config=dict(exchange="okx",product="spot",execution="demo")
    first={"key":"fixture-key","secret":"fixture-secret","passphrase":"fixture-pass"}
    rt.vault.update("okx/demo",first)
    retired,new=Mock(),Mock()
    try:
        with patch("terminal.runtime.Venue",side_effect=[retired,new]) as ctor:
            assert rt.venue(config) is retired
            assert rt.venue(config) is retired
            rt.vault.update("okx/demo",{**first,field:"changed-fixture"})
            assert rt.venue(config) is new
            assert ctor.call_count==2 and len(rt.clients)==1
            retired.client.session.close.assert_called_once()
            assert ctor.call_args.args[3][field]=="changed-fixture"
    finally:rt.shutdown();rt.db.db.close()


def test_failed_new_credentials_never_fall_back_to_old_client(tmp_path):
    rt=Runtime(tmp_path);config=dict(exchange="okx",product="spot",execution="demo")
    rt.vault.update("okx/demo",{"key":"fixture","secret":"first"})
    try:
        with patch("terminal.runtime.Venue",side_effect=[Mock(),ValueError("new credentials failed")]) as ctor:
            rt.venue(config)
            rt.vault.update("okx/demo",{"key":"fixture","secret":"second"})
            with pytest.raises(ValueError,match="new credentials failed"):rt.venue(config)
            assert ctor.call_count==2
    finally:rt.shutdown();rt.db.db.close()


def test_same_named_worker_threads_do_not_share_exchange_client(tmp_path):
    rt=Runtime(tmp_path);config=dict(exchange="okx",product="spot",execution="demo")
    rt.vault.update("okx/demo",{"key":"fixture","secret":"fixture"})
    gate=threading.Barrier(2)
    def worker():
        threading.current_thread().name="AnyIO worker thread"
        gate.wait(timeout=3)
        return rt.venue(config)
    try:
        with patch("terminal.runtime.Venue",side_effect=lambda *args:Mock()):
            with ThreadPoolExecutor(2) as pool:
                first,second=list(pool.map(lambda i:worker(),[1,2]))
        assert first is not second and len(rt.clients)==2
    finally:rt.shutdown();rt.db.db.close()


@pytest.mark.parametrize("qty,status",[(.1,"closed"),(.04,"canceled")])
def test_handover_status_uses_actual_remaining_position(triggered,qty,status):
    rt,ledger,o=triggered
    ledger.settle_children(o["client_id"],receipts(qty,status))
    svc,_=release_service(rt,ledger,o)
    svc.finalize(o["client_id"])
    result=rt.hosted_status()
    assert result["review_required"] and not result["live_creation"]
    if qty==.1:assert result["handover"]==[]
    else:
        assert result["handover"][0]["quantity"]==pytest.approx(.06)
        assert result["handover"][0]["symbol"]=="BTC"
