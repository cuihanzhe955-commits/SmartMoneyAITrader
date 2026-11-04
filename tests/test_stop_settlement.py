import copy

import pytest

from execution.hosted import HostedStops
from terminal.runtime import Runtime
from terminal.config import Session
from test_hosted import detail


@pytest.fixture
def triggered(tmp_path):
    rt = Runtime(tmp_path)
    with rt.db.db:
        s = rt.new(Session(consent=True, capital=100))
        s["config"].update(exchange="okx", execution="demo", product="spot")
        s.update(account_ref="fixture", cash=90)
        s["positions"]["BTC"] = dict(qty=.1, cost=10, price=100, opened=s["t"], opening_order="entry1")
        rt.db.save(s)
    ledger = HostedStops(tmp_path / "terminal.db")
    o = ledger.plan(s, "BTC", 90)
    ledger.begin_create(o["client_id"], s)
    ledger.observe(o["client_id"], detail(o, state="effective", ordIdList=["child1"], actualSz=".1"))
    try:
        yield rt, ledger, o
    finally:
        ledger.close()
        rt.db.db.close()


def receipts(qty=.1, status="closed", fee=.009):
    order = dict(id="child1", symbol="BTC/USDT", side="sell", amount=.1, filled=qty, status=status)
    trades = [dict(id="fill1", order="child1", symbol="BTC/USDT", side="sell", amount=qty,
                   price=90, fee=dict(currency="USDT", cost=fee))]
    return {"child1": (order, trades)}


def test_full_fill_accounts_fee_and_is_idempotent_after_reopen(triggered, tmp_path):
    rt, ledger, o = triggered
    cid = o["client_id"]
    result = ledger.settle_children(cid, receipts())
    assert result["complete"] and result["flat"]
    assert rt.db.load()["cash"] == pytest.approx(98.991)
    assert rt.db.load()["realized"] == pytest.approx(-1.009)
    assert rt.db.load()["fees"] == pytest.approx(.009)
    restarted = HostedStops(tmp_path / "terminal.db")
    try:
        assert restarted.settle_children(cid, receipts()) == result
        assert rt.db.load()["cash"] == pytest.approx(98.991)
        assert rt.db.db.execute("SELECT count(*) FROM venue_executions").fetchone()[0] == 1
        assert not rt.db.load()["admitted"]
    finally:
        restarted.close()


def test_partial_then_cancel_keeps_remaining_position(triggered):
    rt, ledger, o = triggered
    result = ledger.settle_children(o["client_id"], receipts(.04, "open", .0036))
    assert not result["complete"] and not result["flat"]
    assert rt.db.load()["positions"]["BTC"]["qty"] == pytest.approx(.06)
    assert rt.db.db.execute("SELECT count(*) FROM positions").fetchone()[0] == 1
    before = rt.db.load()
    assert ledger.settle_children(o["client_id"], receipts(.04, "canceled", .0036))["complete"]
    assert rt.db.load()["cash"] == before["cash"]
    assert ledger.exit_blocked(o["client_id"])


@pytest.mark.parametrize("problem", ["missing", "symbol", "side", "fee", "filled", "owner", "amount"])
def test_bad_child_data_rolls_back_all_money(triggered, problem):
    rt, ledger, o = triggered
    data = receipts()
    if problem == "missing": data = {}
    elif problem == "symbol": data["child1"][0]["symbol"] = "ETH/USDT"
    elif problem == "side": data["child1"][0]["side"] = "buy"
    elif problem == "fee": data["child1"][1][0]["fee"]["currency"] = "OTHER"
    elif problem == "filled": data["child1"][0]["filled"] = .09
    elif problem == "amount": data["child1"][0]["amount"] = .2
    elif problem == "owner":
        with rt.db.db:
            s = rt.db.load(); s["positions"]["BTC"]["opening_order"] = "other"; rt.db.save(s)
    before = rt.db.load()
    with pytest.raises(ValueError): ledger.settle_children(o["client_id"], data)
    assert rt.db.load() == before
    assert rt.db.db.execute("SELECT count(*) FROM venue_executions").fetchone()[0] == 0
    assert rt.db.db.execute("SELECT count(*) FROM venue_orders").fetchone()[0] == 0


def test_terminal_receipt_conflict_does_not_silently_disappear(triggered):
    rt, ledger, o = triggered
    ledger.settle_children(o["client_id"], receipts())
    before = rt.db.load()
    with pytest.raises(ValueError, match="终态成交"):
        ledger.settle_children(o["client_id"], receipts(fee=.01))
    assert rt.db.load() == before


def test_second_child_failure_rolls_back_first_child_fill(triggered):
    rt, ledger, o = triggered
    ledger.observe(o["client_id"], detail(o, state="effective", ordIdList=["child1", "child2"], actualSz=".1", uTime="1001"))
    data = receipts(.05, fee=.0045)
    data["child1"][0]["amount"] = .05
    other = copy.deepcopy(data["child1"])
    other[0].update(id="child2", filled=.04)
    other[1][0].update(id="fill2", order="child2")
    data["child2"] = other
    before = rt.db.load()
    with pytest.raises(ValueError, match="累计成交"):
        ledger.settle_children(o["client_id"], data)
    assert rt.db.load() == before
    assert rt.db.db.execute("SELECT count(*) FROM venue_orders").fetchone()[0] == 0
    assert rt.db.db.execute("SELECT count(*) FROM fills").fetchone()[0] == 0
    other[0]["filled"] = .05
    assert ledger.settle_children(o["client_id"], data)["flat"]
    assert rt.db.load()["cash"] == pytest.approx(98.991)


def test_read_service_collects_children_without_writes(triggered):
    from unittest.mock import Mock
    from execution.stop_transport import DemoStops
    rt, ledger, o = triggered
    venue = Mock()
    report, trades = receipts()["child1"]
    venue.pair.return_value = "BTC/USDT"
    venue.client.fetch_order.return_value = report
    venue.executions.return_value = trades
    svc = DemoStops(ledger, venue, lambda: rt.db.load())
    svc.guard = Mock(return_value=rt.db.load())
    svc._query = Mock(return_value=ledger.get(o["client_id"]))
    assert svc.settle(o["client_id"])["flat"]
    venue.client.fetch_order.assert_called_once_with("child1", "BTC/USDT")
    venue.client.privatePostTradeOrderAlgo.assert_not_called()
    venue.client.privatePostTradeCancelAlgos.assert_not_called()
