import threading
import time
import pytest
from market.worker import MarketWorker

SCOPE=("okx","paper",1,0)


def wait(worker):
    assert worker.flight.done.wait(2)


def test_slow_fetch_does_not_block_poll_or_grow_a_queue():
    entered,release=threading.Event(),threading.Event();clock=[0.]
    w=MarketWorker(lambda:clock[0])
    def fetch(cancel,deadline):
        entered.set();assert release.wait(2);return {"price":100}
    try:
        assert w.submit(SCOPE,fetch,1);assert entered.wait(2)
        start=time.monotonic()
        assert w.poll(SCOPE) is None
        for _ in range(100):assert not w.submit(SCOPE,fetch,1)
        assert time.monotonic()-start<.2
        clock[0]=1
        assert w.poll(SCOPE)["status"]=="TIMEOUT"
        assert w.poll(SCOPE) is None
        assert not w.submit(SCOPE,fetch,1)  # A timeout does not kill the socket.
        release.set();wait(w);assert w.poll(SCOPE) is None
        assert w.flight is None
    finally:release.set();w.close()


def test_scope_change_rejects_completed_old_venue_or_session_result():
    w=MarketWorker();assert w.submit(SCOPE,lambda *_:{"price":100},10);wait(w)
    assert w.poll(("binance","paper",2,0))["status"]=="STALE"
    assert w.poll(SCOPE) is None


def test_completed_but_expired_result_is_not_returned():
    clock=[0];w=MarketWorker(lambda:clock[0]);w.submit(SCOPE,lambda *_:100,1);wait(w);clock[0]=2
    r=w.poll(SCOPE);assert r["status"]=="TIMEOUT" and r["value"] is None


def test_ready_result_is_copied_and_delivered_once():
    data={"bars":[1]};w=MarketWorker();w.submit(SCOPE,lambda *_:data,10);wait(w)
    data["bars"].append(2)
    assert w.poll(SCOPE)["value"]=={"bars":[1]}
    assert w.poll(SCOPE) is None


def test_fetch_error_does_not_expose_raw_exception():
    def fail(*_):raise RuntimeError("fixture-secret-url-and-key")
    w=MarketWorker();w.submit(SCOPE,fail,10);wait(w)
    r=w.poll(SCOPE);assert r["status"]=="ERROR" and "secret" not in repr(r)


def test_close_cancels_cooperatively_without_waiting_and_permanently_closes():
    entered,release=threading.Event(),threading.Event();w=MarketWorker()
    def fetch(cancel,deadline):
        entered.set();assert release.wait(2);assert cancel.is_set();return 100
    try:
        w.submit(SCOPE,fetch,10);assert entered.wait(2)
        t=time.monotonic();w.close();assert time.monotonic()-t<.2
        assert not w.submit(SCOPE,fetch,10)
        release.set();wait(w);assert w.poll(SCOPE) is None
    finally:release.set()


def test_invalidation_retains_slot_until_old_request_finishes_then_allows_new_work():
    entered,release=threading.Event(),threading.Event();w=MarketWorker()
    def fetch(*_):entered.set();assert release.wait(2);return 100
    try:
        w.submit(SCOPE,fetch,10);assert entered.wait(2);w.invalidate()
        assert not w.submit(SCOPE,fetch,10)
        release.set();wait(w)
        assert w.submit(("okx","paper",1,1),lambda *_:200,10);wait(w)
        assert w.poll(("okx","paper",1,1))["value"]==200
    finally:release.set();w.close()


@pytest.mark.parametrize("timeout",[0,-1,True,float("nan"),float("inf")])
def test_invalid_deadline_is_rejected(timeout):
    with pytest.raises(ValueError):MarketWorker().submit(SCOPE,lambda *_:None,timeout)


def test_thread_start_failure_does_not_leave_a_permanently_occupied_slot():
    from unittest.mock import patch
    w=MarketWorker()
    with patch("market.worker.Thread.start",side_effect=RuntimeError("fixture")):
        assert w.submit(SCOPE,lambda *_:100,10)
    assert w.poll(SCOPE)["status"]=="ERROR"
    assert w.submit(SCOPE,lambda *_:200,10);wait(w)
    assert w.poll(SCOPE)["value"]==200
