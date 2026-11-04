import json
from unittest.mock import Mock

import pytest

from execution.protection_report import report
from terminal.runtime import Runtime
from test_stop_runtime import active
from test_stop_settlement import triggered, receipts


def test_report_explains_durable_states_and_never_exports_secrets(active):
    rt,ledger,o,v=active
    rt.hosted_tick()
    with ledger.db:
        row=ledger.db.execute("SELECT id,body FROM hosted_stop_events LIMIT 1").fetchone()
        body=json.loads(row[1]);body.update(api_key="private-fixture",account_ref="private-binding",raw_response={"secret":"private-secret"})
        ledger.db.execute("UPDATE hosted_stop_events SET body=? WHERE id=?",(json.dumps(body),row[0]))
    before=rt.db.load()
    result=rt.hosted_report(before["id"],o["client_id"])
    assert [e["id"] for e in result["events"]]==sorted(e["id"] for e in result["events"])
    assert "SENDING" in [e["stage"] for e in result["events"]]
    assert not result["real_funds_verified"] and not result["platform_integration_verified"]
    assert all(e["recorded_at"] for e in result["events"])
    assert "private-" not in json.dumps(result)
    assert rt.db.load()==before
    v.client.create_order.assert_not_called();v.client.cancel_order.assert_not_called()


def test_legacy_missing_time_is_unknown_not_fabricated(active):
    rt,ledger,o,v=active
    with ledger.db:
        rows=ledger.db.execute("SELECT id,body FROM hosted_stop_events").fetchall()
        for key,raw in rows:
            body=json.loads(raw);body.pop("recorded_at",None)
            ledger.db.execute("UPDATE hosted_stop_events SET body=? WHERE id=?",(json.dumps(body),key))
    result=rt.hosted_report(rt.db.load()["id"],o["client_id"])
    assert result["events"] and all(e["recorded_at"] is None for e in result["events"])


def test_pagination_is_bounded_and_has_no_overlapping_events(active):
    rt,ledger,o,v=active
    for i in range(120):ledger.maintenance_result(o["client_id"],i,False)
    cid=rt.db.load()["id"]
    first=rt.hosted_report(cid,o["client_id"])
    assert len(first["events"])==100 and first["has_more"]
    second=rt.hosted_report(cid,o["client_id"],first["next_before"])
    assert not second["has_more"]
    assert not set(e["id"] for e in first["events"]) & set(e["id"] for e in second["events"])
    assert max(e["id"] for e in second["events"]) < min(e["id"] for e in first["events"])


@pytest.mark.parametrize("case",["session","missing","negative","boolean"])
def test_report_rejects_wrong_scope_or_invalid_cursor(active,case):
    rt,ledger,o,v=active
    cid=rt.db.load()["id"]
    with pytest.raises(ValueError):
        rt.hosted_report(cid+1 if case=="session" else cid,"missing" if case=="missing" else o["client_id"],-1 if case=="negative" else True if case=="boolean" else 0)


def test_read_only_report_does_not_initialize_protection_schema(tmp_path):
    rt=Runtime(tmp_path)
    try:
        before=rt.db.db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        with pytest.raises(ValueError,match="没有可读取"):rt.hosted_report(1,"fixture")
        assert rt.db.db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]==before
    finally:rt.shutdown();rt.db.db.close()


@pytest.mark.parametrize("qty,status",[(.1,"closed"),(.04,"open")])
def test_child_costs_are_exact_existing_ledger_receipts(triggered,qty,status):
    rt,ledger,o=triggered
    ledger.settle_children(o["client_id"],receipts(qty,status,fee=.0036))
    before=rt.db.load()
    result=rt.hosted_report(before["id"],o["client_id"])
    child=result["children"][0]
    assert child["receipt"]["qty"]==qty
    assert child["receipt"]["nominal"]==pytest.approx(qty*90)
    assert child["receipt"]["fee"]==.0036
    assert child["receipt"]["pnl"]==pytest.approx(qty*90-.0036-qty*100)
    assert child["stage"]==("FILLED" if qty==.1 else "PARTIALLY_FILLED")
    assert rt.db.load()==before
