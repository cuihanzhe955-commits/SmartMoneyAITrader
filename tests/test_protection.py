import copy
import pytest
from execution.protection import audit_protection
from execution.health import inspect_session, latest_report
from terminal.runtime import Runtime


def position(qty=1):
    return {"positions": {"BTC": {"qty": qty}}}


def stop(**changes):
    return {**dict(algoId="fixture-stop", instId="BTC-USDT", instType="SPOT", tdMode="cash",
                   ordType="conditional", side="sell", state="live", sz="1", slTriggerPx="90", slOrdPx="-1"), **changes}


def test_matching_quantity_does_not_grant_hosted_protection():
    state, rows = position(), [stop()]
    before = copy.deepcopy((state, rows))
    result = audit_protection(state, rows)
    assert result["positions"][0]["status"] == "quantity_matches_unverified"
    assert not result["exchange_protection_verified"] and "归属" in result["issues"][0]
    assert (state, rows) == before


@pytest.mark.parametrize("change,reason", [
    ({"state": "effective"}, "待触发"), ({"state": "canceled"}, "待触发"),
    ({"side": "buy"}, "卖出"), ({"instType": "SWAP"}, "现金现货"),
    ({"tdMode": "cross"}, "现金现货"), ({"sz": "NaN"}, "数量或触发"),
    ({"slTriggerPx": "0"}, "数量或触发"), ({"slOrdPx": ""}, "委托价格"),
    ({"instId": "ETH-USDT"}, "策略持仓"),
])
def test_invalid_or_inapplicable_order_is_not_counted(change, reason):
    result = audit_protection(position(), [stop(**change)])
    assert any(reason in text for text in result["issues"])
    assert result["positions"][0]["observed_stop_quantity"] == "0"
    assert not result["exchange_protection_verified"]


@pytest.mark.parametrize("qty", ["0.4", "1.2"])
def test_partial_position_and_excess_stop_quantities_are_explained(qty):
    result = audit_protection(position(), [stop(sz=qty)])
    assert result["positions"][0]["status"] == "quantity_mismatch"
    assert any(qty in text and "不一致" in text for text in result["issues"])


def test_duplicate_id_is_not_double_counted():
    result = audit_protection(position(), [stop(), stop()])
    assert result["positions"][0]["observed_stop_quantity"] == "1"
    assert any("标识缺失或重复" in text for text in result["issues"])


def test_multiple_orders_need_separate_review_even_if_total_matches():
    result = audit_protection(position(), [stop(sz="0.4"), stop(algoId="other", sz="0.6")])
    assert result["positions"][0]["observed_stop_quantity"] == "1.0"
    assert any("重复触发" in text for text in result["issues"])
    assert not result["exchange_protection_verified"]


def test_missing_stop_and_orphan_stop_are_visible():
    assert audit_protection(position(), [])["positions"][0]["status"] == "missing"
    assert any("策略持仓" in text for text in audit_protection({"positions": {}}, [stop()])["issues"])


@pytest.mark.parametrize("case,status,reason", [
    ("missing", "READ_ONLY_PASSED", "未发现"),
    ("short", "BLOCKED", "不一致"),
    ("matching", "BLOCKED", "归属"),
    ("triggered", "BLOCKED", "待触发"),
    ("orphan", "BLOCKED", "策略持仓"),
])
def test_protection_differences_reach_persisted_readiness_report(tmp_path, case, status, reason):
    from test_acceptance import remote, health_venue
    rt = Runtime(tmp_path)
    try:
        state = remote(rt)
        venue = health_venue(rt)
        if case != "orphan":
            with rt.db.db:
                state["positions"]["BTC"] = dict(qty=1, cost=100, opened=state["t"],
                                                entry=100, price=100, high=100)
                rt.db.save(state)
        rows = [] if case == "missing" else [stop(
            sz="0.4" if case == "short" else "1", state="effective" if case == "triggered" else "live")]
        venue.algo_inventory.return_value = rows
        before = rt.db.load()
        report = inspect_session(rt, state["id"])
        assert report["status"] == status and not report["authorizes_trading"]
        key = "algo_positions" if case == "missing" else "algo_inventory"
        check = next(c for c in report["checks"] if c["key"] == key)
        assert reason in check["message"]
        assert not check["details"]["exchange_protection_verified"]
        if case == "short":
            comparison = check["details"]["positions"][0]
            assert comparison["position_quantity"] == "1"
            assert comparison["observed_stop_quantity"] == "0.4"
        assert rt.db.load() == before and latest_report(rt, state["id"]) == report
        venue.submit.assert_not_called()
        venue.client.cancel_order.assert_not_called()
        venue.client.create_order.assert_not_called()
    finally:
        rt.db.db.close()


def test_position_change_during_protection_check_invalidates_report(tmp_path):
    from test_acceptance import remote, health_venue
    rt = Runtime(tmp_path)
    try:
        state = remote(rt)
        venue = health_venue(rt)
        def changed():
            with rt.lock, rt.db.db:
                current = rt.db.load()
                current["positions"]["BTC"] = dict(qty=1, cost=100, opened=current["t"],
                                                  entry=100, price=100, high=100)
                rt.db.save(current)
            return []
        venue.algo_inventory.side_effect = changed
        report = inspect_session(rt, state["id"])
        ledger = next(c for c in report["checks"] if c["key"] == "ledger")
        assert report["status"] == "BLOCKED" and ledger["status"] == "FAIL"
        assert "变化" in ledger["message"] and not report["authorizes_trading"]
        venue.submit.assert_not_called()
    finally:
        rt.db.db.close()


@pytest.mark.parametrize("quantity", [None, "0.4", "1"])
def test_restart_keeps_protection_evidence_without_restoring_trading_authority(tmp_path, quantity):
    from unittest.mock import patch
    from test_acceptance import health_venue
    from test_phase4 import exchange_session
    rt = Runtime(tmp_path)
    try:
        state = exchange_session(rt)
        with rt.db.db:
            state["positions"]["BTC"] = dict(qty=1, cost=100, opened=state["t"],
                                             entry=100, price=100, high=100)
            state["cash"] = 0
            rt.db.save(state)
        venue = health_venue(rt)
        venue.algo_inventory.return_value = [] if quantity is None else [stop(sz=quantity)]
        report = inspect_session(rt, state["id"])
        assert report["status"] == ("READ_ONLY_PASSED" if quantity is None else "BLOCKED")
        assert rt.db.load()["admitted"] and rt.db.load()["local_armed"]
    finally:
        rt.shutdown()
        rt.db.db.close()
    restarted = Runtime(tmp_path)
    try:
        # Exercise startup recovery without network loops or real account access.
        with patch.object(restarted, "loop"):
            restarted.start_worker()
        before = restarted.db.load()
        restored = latest_report(restarted, state["id"])
        assert restored["checks"] == report["checks"] and not restored["authorizes_trading"]
        assert restored["requires_recheck"] and any("重启" in r for r in restored["recheck_reasons"])
        checks = [c for c in restored["checks"] if c["key"] in ("algo_inventory", "algo_positions")]
        assert checks and not checks[0]["details"]["exchange_protection_verified"]
        assert before["lifecycle_status"] == "PAUSED"
        assert not before["admitted"] and not before["local_armed"]
        assert before["needs_check"] and before["recovery_required"]
        assert before["positions"]["BTC"]["qty"] == 1
        assert restarted.db.load() == before
        assert restarted.db.db.execute("SELECT COUNT(*) FROM venue_orders").fetchone()[0] == 0
    finally:
        restarted.shutdown()
        restarted.db.db.close()


@pytest.mark.parametrize("change", ["age", "position", "config", "credentials"])
def test_cached_report_staleness_is_read_only(tmp_path, change):
    from unittest.mock import patch
    from test_acceptance import remote, health_venue
    rt = Runtime(tmp_path)
    try:
        state = remote(rt)
        health_venue(rt)
        report = inspect_session(rt, state["id"])
        assert not latest_report(rt, state["id"])["requires_recheck"]
        if change in ("position", "config"):
            with rt.db.db:
                current = rt.db.load()
                if change == "config": current["config"]["stop"] += 1
                else: current["cash"] -= 1
                rt.db.save(current)
        elif change == "credentials":
            rt.vault.update("okx/live", {"key": "different-fixture"})
        before = rt.db.load()
        with patch("execution.health.time.time", return_value=report["finished_at"] + (61 if change == "age" else 1)):
            stale = latest_report(rt, state["id"])
        assert stale["requires_recheck"] and stale["recheck_reasons"]
        assert stale["checks"] == report["checks"] and not stale["authorizes_trading"]
        assert rt.db.load() == before
        assert not rt.db.load().get("admitted")
    finally:
        rt.db.db.close()
