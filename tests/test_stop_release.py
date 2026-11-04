import json
import sqlite3
import time
from unittest.mock import Mock

import pytest

from execution import live
from execution.hosted import HostedStops
from execution.stop_transport import DemoStops
from test_stop_settlement import triggered, receipts


def release_service(rt, ledger, o):
    v = Mock()
    v.audit_spot.return_value = {"dedicated_balance_match": True}
    v.algo_inventory.return_value = []
    service = DemoStops(ledger, v, lambda: rt.db.load(), rt.lock)
    service.guard = Mock(side_effect=lambda order: rt.db.load())
    return service, v


@pytest.mark.parametrize("qty,status",[(.1,"closed"),(.04,"canceled")])
def test_confirmed_account_release_keeps_residual_paused(triggered, qty, status):
    rt, ledger, o = triggered
    ledger.settle_children(o["client_id"],receipts(qty,status))
    svc,v = release_service(rt,ledger,o)
    released = svc.finalize(o["client_id"])
    assert released["released"] and not ledger.exit_blocked(o["client_id"])
    assert not live.hosted_pending(rt.db)
    s = rt.db.load()
    assert s["lifecycle_status"] == "PAUSED" and not s["admitted"] and not s["local_armed"]
    assert s["hosted_review_required"]
    rt.admit=Mock(side_effect=AssertionError("must not auto re-admit after protection release"))
    rt.tick()
    rt.admit.assert_not_called()
    assert bool(s["positions"]) == (qty < .1)
    before = s.copy()
    assert svc.finalize(o["client_id"])["released"]
    assert rt.db.load() == before
    assert len(rt.db.entries("system_events",s["id"],kind="HOSTED_RELEASED")) == 1
    if qty < .1:
        replacement=ledger.plan(s,"BTC",89,generation=1)
        assert replacement["quantity"] == str(s["positions"]["BTC"]["qty"])
        assert replacement["client_id"] != o["client_id"] and live.hosted_pending(rt.db)
        assert ledger.plan(s,"BTC",89,generation=1)["client_id"] == replacement["client_id"]


@pytest.mark.parametrize("problem",["balance","external","changed","expired","incomplete","missingproof"])
def test_failed_finalization_never_releases(triggered, problem):
    rt,ledger,o=triggered
    ledger.settle_children(o["client_id"],receipts(.04,"open" if problem=="incomplete" else "canceled"))
    svc,v=release_service(rt,ledger,o)
    if problem=="balance":v.audit_spot.return_value={"dedicated_balance_match":False}
    if problem=="external":v.algo_inventory.return_value=[{"algoId":"external"}]
    if problem=="changed":
        def audit(s):
            with rt.db.db:
                current=rt.db.load();current["cash"]-=1;rt.db.save(current)
            return {"dedicated_balance_match":True}
        v.audit_spot.side_effect=audit
    if problem=="missingproof":
        with rt.db.db:
            body=json.loads(rt.db.db.execute("SELECT body FROM venue_orders").fetchone()[0]);body.pop("terminal_proof")
            rt.db.db.execute("UPDATE venue_orders SET body=?",(json.dumps(body),))
    with pytest.raises(ValueError):
        if problem=="expired":ledger.release_checked(o["client_id"],rt.db.load(),time.time()-11)
        else:svc.finalize(o["client_id"])
    assert ledger.exit_blocked(o["client_id"]) and live.hosted_pending(rt.db)


def test_replacement_blocked_until_previous_release(triggered):
    rt,ledger,o=triggered
    ledger.settle_children(o["client_id"],receipts(.04,"canceled"))
    with pytest.raises(ValueError,match="重复创建"):
        ledger.plan(rt.db.load(),"BTC",89,generation=1)


def test_old_index_migration_preserves_all_records(triggered,tmp_path):
    rt,ledger,o=triggered
    before=ledger.get(o["client_id"])
    with ledger.db:
        ledger.db.execute("DROP INDEX hosted_stop_slot")
        ledger.db.execute("CREATE UNIQUE INDEX hosted_stop_slot ON hosted_stops(slot) WHERE stage NOT IN ('CANCELED','FAILED')")
    reopened=HostedStops(tmp_path/"terminal.db")
    try:
        assert reopened.get(o["client_id"])==before
        assert "released" in reopened.db.execute("SELECT sql FROM sqlite_master WHERE name='hosted_stop_slot'").fetchone()[0]
    finally:reopened.close()
