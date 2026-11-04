"""Ledger identity checks must survive adapters returning contradictory data."""
import time
from unittest.mock import Mock

import pytest

from execution import live
from terminal.runtime import Runtime
from test_phase4 import exchange_session


@pytest.fixture
def receipt_runtime(tmp_path):
    rt = Runtime(tmp_path)
    state = exchange_session(rt)
    with rt.db.db:
        live.enqueue(rt.db, state, "BTC", "BUY", {"price": 10, "time": int(time.time())}, 20, "fixture")
        intent = live.pending(rt.db, state["id"])
        intent["prepared"] = dict(quantity=2, price=10, contract=1)
        live.save(rt.db, intent, "SENDING")
    venue = Mock()
    rt.venue = lambda c: venue
    venue.lookup.return_value = dict(id="receipt-fixture", status="closed", filled=2,
                                    clientOrderId=intent["client_id"], symbol="BTC/USDT", side="buy", amount=2)
    venue.executions.return_value = [dict(id="fill-fixture", order="receipt-fixture", symbol="BTC/USDT",
                                         side="buy", price=10, amount=2, fee=dict(currency="USDT", cost=0))]
    try:
        yield rt, state, intent, venue
    finally:
        rt.shutdown()
        rt.db.db.close()


@pytest.mark.parametrize("field,value", [
    ("clientOrderId", "another-intent"), ("symbol", "ETH/USDT"), ("side", "sell"),
])
def test_conflicting_order_identity_cannot_move_cash_or_clear_pending(receipt_runtime, field, value):
    rt, state, intent, venue = receipt_runtime
    venue.lookup.return_value[field] = value
    rt.dispatch(state, intent)
    current = rt.db.load()
    assert current["cash"] == 100 and not current["positions"]
    assert current["lifecycle_status"] == "PAUSED" and current["recovery_required"]
    assert live.pending(rt.db, state["id"])["stage"] == "UNKNOWN"
    assert not rt.db.entries("fills", state["id"])
    assert rt.db.db.execute("SELECT COUNT(*) FROM venue_executions").fetchone()[0] == 0
    venue.submit.assert_not_called()
    venue.cancel.assert_not_called()


def test_trade_symbol_is_checked_against_durable_intent_with_sparse_order(receipt_runtime):
    rt, state, intent, venue = receipt_runtime
    venue.lookup.return_value.pop("symbol")
    venue.executions.return_value[0]["symbol"] = "ETH/USDT"
    rt.dispatch(state, intent)
    assert live.pending(rt.db, state["id"])["stage"] == "UNKNOWN"
    assert rt.db.load()["cash"] == 100 and not rt.db.load()["positions"]


def test_valid_trade_symbol_with_sparse_order_is_not_rejected(receipt_runtime):
    rt, state, intent, venue = receipt_runtime
    venue.lookup.return_value.pop("symbol")
    rt.dispatch(state, intent)
    assert live.pending(rt.db, state["id"]) is None
    assert rt.db.load()["cash"] == 80 and rt.db.load()["positions"]["BTC"]["qty"] == 2


def test_original_client_id_fallback_remains_supported(receipt_runtime):
    rt, state, intent, venue = receipt_runtime
    venue.lookup.return_value.update(clientOrderId=None, info={"origClientOrderId": intent["client_id"]})
    rt.dispatch(state, intent)
    assert live.pending(rt.db, state["id"]) is None
    assert rt.db.load()["positions"]["BTC"]["qty"] == 2


def test_wrong_session_cannot_settle_another_sessions_order(receipt_runtime):
    rt, state, intent, venue = receipt_runtime
    state["id"] += 1
    with rt.db.db, pytest.raises(ValueError, match="会话"):
        live.settle(rt.db, state, intent, venue.lookup.return_value, venue.executions.return_value)
    assert rt.db.load()["cash"] == 100 and not rt.db.load()["positions"]
    assert rt.db.db.execute("SELECT COUNT(*) FROM venue_executions").fetchone()[0] == 0
