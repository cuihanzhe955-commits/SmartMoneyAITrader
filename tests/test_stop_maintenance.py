import threading
from unittest.mock import Mock

import pytest

from execution.hosted import HostedStops
from execution.stop_maintenance import StopMaintenance
from test_hosted import state, detail


@pytest.fixture
def worker(tmp_path):
    ledger = HostedStops(tmp_path / "ledger.db")
    o = ledger.plan(state(), "BTC", 90)
    ledger.begin_create(o["client_id"], state())
    svc = Mock(ledger=ledger)
    svc.reconcile.side_effect = lambda cid: ledger.observe(cid, detail(o))
    clock = Mock(return_value=100)
    lane = StopMaintenance(svc, clock)
    try:
        yield lane, svc, ledger, o, clock
    finally:
        lane.stop()
        ledger.close()


def test_recovery_queries_original_intent_and_never_writes(worker):
    lane,svc,ledger,o,clock=worker
    assert lane.once()==[dict(client_id=o["client_id"],checked=True)]
    assert ledger.get(o["client_id"])["stage"]=="LIVE"
    assert lane.once()==[]
    clock.return_value=105
    assert lane.once()[0]["checked"]
    svc.create.assert_not_called(); svc.cancel.assert_not_called()


def test_failure_backoff_survives_reopen_and_hides_raw_error(worker,tmp_path):
    lane,svc,ledger,o,clock=worker
    svc.reconcile.side_effect=TimeoutError("private-secret-response")
    assert not lane.once()[0]["checked"]
    restarted=HostedStops(tmp_path/"ledger.db")
    try:
        saved=restarted.get(o["client_id"])
        assert saved["next_check"]==102 and "private-secret" not in str(saved)
        assert restarted.due(101)==[]
        assert restarted.due(102)[0]["client_id"]==o["client_id"]
    finally: restarted.close()


def test_triggered_order_uses_existing_fill_reconciliation(worker):
    lane,svc,ledger,o,clock=worker
    ledger.observe(o["client_id"],detail(o,state="effective",ordIdList=["child1"],actualSz=".1"))
    lane.once()
    svc.settle.assert_called_once_with(o["client_id"])
    svc.create.assert_not_called(); svc.cancel.assert_not_called()


def test_concurrent_maintenance_cannot_duplicate_work(worker):
    lane,svc,ledger,o,clock=worker
    entered,release=threading.Event(),threading.Event()
    def slow(cid):
        entered.set(); release.wait(2)
        return ledger.observe(cid,detail(o))
    svc.reconcile.side_effect=slow
    lane.start()
    try:
        assert entered.wait(1)
        assert lane.once()==[]
        assert not lane.stop(.01)
        assert svc.reconcile.call_count==1
    finally:
        release.set(); assert lane.stop(2)


@pytest.mark.parametrize("limit",[0,21,True,1.5])
def test_invalid_budget_rejected(worker,limit):
    with pytest.raises(ValueError):worker[0].once(limit)
