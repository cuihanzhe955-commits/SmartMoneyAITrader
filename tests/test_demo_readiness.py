import json
import time
from unittest.mock import patch

import pytest

from execution.demo_readiness import inspect_local
from execution.health import inspect_session, latest_report
from execution import live
from terminal.runtime import Runtime
from terminal.config import Session
from test_acceptance import health_venue
from execution.hosted import HostedStops


@pytest.fixture
def demo(tmp_path):
    rt=Runtime(tmp_path)
    rt.vault.update("okx/demo",dict(key="fixture-key",secret="fixture-secret",passphrase="fixture-passphrase"))
    with rt.db.db:
        state=rt.new(Session(consent=True,execution="demo",source="public",capital=100))
    venue=health_venue(rt)
    try:yield rt,state,venue
    finally:rt.shutdown();rt.db.db.close()


def test_empty_setup_reports_actionable_fields_without_network_or_writes(tmp_path):
    rt=Runtime(tmp_path)
    try:
        before=rt.db.db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        with patch("terminal.runtime.Venue",side_effect=AssertionError("local only")):
            result=inspect_local(rt)
        assert not result["can_run_readonly"] and not result["prereqs_ready"]
        assert "API Key" in result["steps"][0]["message"]
        assert rt.db.load() is None
        assert rt.db.db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]==before
    finally:rt.shutdown();rt.db.db.close()


def test_fresh_readonly_report_is_not_platform_or_trading_authority(demo):
    rt,s,v=demo
    before=rt.db.load()
    assert inspect_local(rt)["can_run_readonly"]
    assert not inspect_local(rt)["prereqs_ready"]
    report=inspect_session(rt,s["id"])
    result=inspect_local(rt)
    assert result["prereqs_ready"] and result["read_only"]
    assert not result["platform_integration_verified"] and not result["real_funds_verified"] and not result["authorizes_trading"]
    assert result["steps"][-1]["status"]=="NOT_VERIFIED"
    assert rt.db.load()==before
    payload=json.dumps([result,report,latest_report(rt,s["id"])])
    assert "_credential_version" not in payload and "fixture-secret" not in payload and "fixture-key" not in payload
    v.submit.assert_not_called();v.client.create_order.assert_not_called()


@pytest.mark.parametrize("field",["key","secret","passphrase"])
def test_all_credential_changes_invalidate_preflight(demo,field):
    rt,s,v=demo
    inspect_session(rt,s["id"])
    rt.vault.update("okx/demo",{**rt.vault.values["okx/demo"],field:"changed-fixture"})
    result=latest_report(rt,s["id"])
    assert result["requires_recheck"]
    assert not inspect_local(rt)["prereqs_ready"]
    assert "_credential_version" not in result


def test_secret_change_during_checks_blocks_report(demo):
    rt,s,v=demo
    def changed():
        rt.vault.update("okx/demo",{**rt.vault.values["okx/demo"],"secret":"changed-fixture"})
        return {"market_rules":"verified"}
    v.market_check.side_effect=changed
    report=inspect_session(rt,s["id"])
    assert report["status"]=="BLOCKED"
    assert next(c for c in report["checks"] if c["key"]=="ledger")["status"]=="FAIL"


def test_old_report_without_credential_version_requires_new_check(demo):
    rt,s,v=demo
    report=inspect_session(rt,s["id"])
    with rt.db.db:
        raw=json.loads(rt.db.db.execute("SELECT body FROM acceptance_reports WHERE id=?",(report["id"],)).fetchone()[0])
        raw.pop("_credential_version")
        rt.db.db.execute("UPDATE acceptance_reports SET body=? WHERE id=?",(json.dumps(raw),report["id"]))
    assert latest_report(rt,s["id"])["requires_recheck"]


def test_expired_report_cannot_mark_prerequisites_ready(demo):
    rt,s,v=demo
    report=inspect_session(rt,s["id"])
    with patch("execution.health.time.time",return_value=report["finished_at"]+61):
        assert not inspect_local(rt)["prereqs_ready"]


def test_unconfirmed_order_blocks_demo_preparation(demo):
    rt,s,v=demo
    with rt.db.db:
        live.enqueue(rt.db,s,"BTC","BUY",dict(price=100,time=int(time.time())),10,"fixture")
        live.save(rt.db,live.pending(rt.db,s["id"]),"UNKNOWN")
    result=inspect_local(rt)
    assert not result["can_run_readonly"]
    assert next(c for c in result["steps"] if c["key"]=="orders")["status"]=="BLOCKED"


@pytest.mark.parametrize("missing",["key","secret","passphrase"])
def test_incomplete_credentials_do_not_enable_check_button(demo,missing):
    rt,s,v=demo
    rt.vault.update("okx/demo",{**rt.vault.values["okx/demo"],missing:" "})
    assert not inspect_local(rt)["can_run_readonly"]


def test_new_protection_intent_invalidates_report_even_without_position_change(demo):
    rt,s,v=demo
    with rt.db.db:
        s["positions"]["BTC"]=dict(qty=.1,cost=10,price=100,opened=s["t"],opening_order="fixture")
        rt.db.save(s)
    inspect_session(rt,s["id"])
    assert not latest_report(rt,s["id"])["requires_recheck"]
    ledger=HostedStops(rt.root/"terminal.db")
    try:ledger.plan(s,"BTC",90)
    finally:ledger.close()
    refreshed=latest_report(rt,s["id"])
    assert refreshed["requires_recheck"] and any("保护记录" in reason for reason in refreshed["recheck_reasons"])
    assert not inspect_local(rt)["prereqs_ready"]
    assert "_ledger_version" not in refreshed
