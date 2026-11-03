"""Regression checks for configurable risk and the sizing explanation contract."""
import json
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from challenge.config import DEFAULT
from challenge.manager import create, scan
from challenge.validation import config
from events.store import Store
from execution.paper_queue import queue, drain
from execution import live
from market.feeds import START, historical
from risk.limits import allowance
from terminal.api import create_app
from terminal.config import Session
from terminal.runtime import Runtime


def sizing_config(**changes):
    return {**DEFAULT, "target": 100, "concentration": 100, "utilization": 100,
            "stop": 2, "fee": 0, "cooldown": 0, "strict_min": 1, **changes}


def portfolio(cash=100):
    return {"cash": cash, "positions": {}, "t": START, "last_buy": 0}


@pytest.mark.parametrize("risk,expected", [(0.5, 25), (1, 50), (2, 100)])
def test_budget_changes_actual_size(risk, expected):
    amount, _, caps = allowance(portfolio(), sizing_config(risk_per_trade_pct=risk), {"slip": 0})
    assert amount == expected
    detail = caps["calculation"]
    assert detail["final_amount"] == amount and detail["final_pct"] == expected
    assert detail["risk_budget"] == risk


def test_legacy_default_and_trade_costs():
    c = sizing_config(fee=0.1)
    c.pop("risk_per_trade_pct")
    amount, _, caps = allowance(portfolio(1000), c, {"slip": 0.001})
    expected = (1000 * 0.01 / (0.02 + 2 * (0.001 + 0.001))) / 1.001
    assert amount == pytest.approx(expected)
    assert caps["calculation"]["compatibility_default"]
    assert caps["calculation"]["estimated_fee"] == pytest.approx(amount * 0.001)
    assert caps["calculation"]["binding_limits"] == ["风险预算"]
    json.dumps(caps, allow_nan=False)


@pytest.mark.parametrize("change,reason", [
    ({"slots": 0}, "持仓数量"), ({"cooldown": START + 1}, "冷却"),
    ({"strict_min": 51}, "最小订单"), ({"utilization": 0}, "资金"),
])
def test_rejections_keep_complete_calculation(change, reason):
    amount, why, caps = allowance(portfolio(), sizing_config(**change), {"slip": 0})
    assert amount == 0 and reason in why
    assert len(caps["calculation"]["limits"]) == 5
    assert caps["calculation"]["final_amount"] == 0


def test_balance_and_exposure_caps():
    s = portfolio(10)
    s["positions"]["ETH"] = {"qty": 1, "price": 90}
    amount, _, caps = allowance(s, sizing_config(risk_per_trade_pct=5), {"slip": 0})
    assert amount == 10 and set(caps["calculation"]["binding_limits"]) == {"资金利用率", "可用余额"}
    amount, _, caps = allowance(s, sizing_config(utilization=95, risk_per_trade_pct=5), {"slip": 0})
    assert amount == 5 and caps["calculation"]["binding_limits"] == ["资金利用率"]


@pytest.mark.parametrize("field,value", [
    ("risk_per_trade_pct", 0), ("risk_per_trade_pct", True), ("target", 101),
    ("fee", -1), ("stop", 100), ("frame", 49), ("trend", 81),
    ("slots", 21), ("slots", 1.5), ("risk_per_trade_pct", float("nan")),
    ("risk_per_trade_pct", float("inf")), ("interval", True), ("trend", 0),
])
def test_both_configuration_paths_reject_invalid(field, value):
    with pytest.raises(ValueError):
        Session(consent=True, **{field: value})
    with pytest.raises(ValueError):
        config({"consent": True, field: value})


def test_recommended_limits_do_not_clamp():
    values = dict(target=80, risk_per_trade_pct=3, slots=6, candidates=60,
                  interval=1, decision_interval=15, utilization=99,
                  concentration=90, cooldown=0, fee=0, stop=0.2)
    session = Session(consent=True, **values)
    saved = session.settings()
    for key, value in values.items():
        assert saved[key] == value
    assert "risk_per_trade_pct" in {w["field"] for w in session.warnings()}
    old = config({"consent": True, **values})
    for key in DEFAULT:
        if key in values:
            assert old[key] == values[key]


def test_queue_rechecks_budget_and_reports_precision(tmp_path):
    db = Store(tmp_path / "paper.db")
    try:
        c = sizing_config(profile="challenge", risk_per_trade_pct=0.5, paper_rules="venue")
        c["precision_rules"] = {"BTC": dict(tick=0.01, step=0.1, minimum=0.1, min_cost=1)}
        with db.db:
            s = create(db, {}, validated=c)
            m = dict(price=10, time=START, slip=0, valid=True)
            queue(db, s, "BTC", "BUY", m, 40, "fixture")
            s["cash"] = 50
            s["t"] = START + 60
            drain(db, s, [dict(m, symbol="BTC", time=START + 60)])
            fill = db.entries("fills", s["id"])[0]["data"]
            assert fill["nominal"] == 12
            detail = fill["calculation"]
            assert detail["final_amount"] == 12
            assert detail["reason"] == "限制原因：数量步长取整"
            assert db.entries("risk_checks", s["id"])[0]["data"]["calculation"] == detail
    finally:
        db.db.close()


def test_quote_rule_rejection_is_explained(tmp_path):
    db = Store(tmp_path / "paper.db")
    try:
        c = sizing_config(profile="challenge", paper_rules="venue")
        c["precision_rules"] = {"BTC": dict(tick=0.01, step=0.1, minimum=1, min_cost=51)}
        with db.db:
            s = create(db, {}, validated=c)
            m = dict(price=10, time=START, slip=0, valid=True)
            queue(db, s, "BTC", "BUY", m, 50, "fixture")
            s["t"] += 60
            drain(db, s, [dict(m, symbol="BTC", time=START + 60)])
            record = db.entries("risk_checks", s["id"])[0]
            assert record["kind"] == "REJECT"
            assert record["data"]["calculation"]["final_amount"] == 0
            assert record["data"]["calculation"]["rule_min_cost"] == 51
            assert not db.entries("fills", s["id"])
    finally:
        db.db.close()


def test_api_roundtrip_preserves_values_and_authorization(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        fields = client.get("/api/parameters").json()
        assert fields["risk_per_trade_pct"]["high"] == 2
        r = client.post("/api/sessions", json={"consent": True, "target": 80, "risk_per_trade_pct": 3})
        assert r.status_code == 200 and r.json()["warnings"]
        state = client.get("/api/state").json()["state"]
        assert state["config"]["target"] == 80 and state["config"]["risk_per_trade_pct"] == 3
        assert state["lifecycle_status"] == "CREATED" and state["config"]["execution"] == "paper"
        r = client.post("/api/sessions", json={"consent": True, "execution": "live",
                                              "source": "public", "risk_per_trade_pct": 3})
        assert r.status_code == 422


def test_scan_links_risk_and_decision(tmp_path):
    rt = Runtime(tmp_path)
    try:
        with rt.db.db:
            s = rt.new(Session(consent=True, profile="challenge"))
            for minute in range(30):
                scan(rt.db, s, START + minute * 60, historical(START + minute * 60))
            decisions = [d for d in rt.db.entries("decisions", s["id"]) if "calculation" in d["data"]]
            assert decisions
            for d in decisions:
                assert d["data"]["amount"] == d["data"]["calculation"]["final_amount"]
    finally:
        rt.db.db.close()


@pytest.mark.parametrize("oversized", [False, True])
def test_live_dispatch_rechecks_size_before_submit(tmp_path, oversized):
    rt = Runtime(tmp_path)
    venue = Mock()
    rt.venue = lambda c: venue
    venue.preflight.return_value = {"venue_account_id":"mock", "dedicated_balance_match":True, "checked":time.time()}
    venue.audit.return_value = {"dedicated_balance_match":True}
    venue.submit.return_value = {"id": "mock-exchange-order"}
    venue.prepare.side_effect = lambda symbol, side, amount, *args: {
        "quantity": 100 if oversized else amount / 10, "price": 10, "contract": 1, "quote_time":time.time(),
    }
    try:
        with rt.db.db:
            rt.vault.update("okx/live", {"key": "fixture"})
            s = rt.new(Session(
                consent=True, confirmation="启用实盘", execution="live", source="public",
                capital=100, target=100, concentration=100, utilization=100,
                stop=2, risk_per_trade_pct=0.5, fee=0, cooldown=0,
            ))
            s["lifecycle_status"] = "RUNNING"
            rt.db.save(s)
            live.enqueue(rt.db, s, "BTC", "BUY",
                         {"price": 10, "slip": 0, "time": int(time.time())}, 40, "fixture")
        rt.dispatch(s, live.pending(rt.db, s["id"]))
        assert venue.prepare.call_args.args[2] < 40
        row = rt.db.db.execute("select body from venue_orders").fetchone()
        order = json.loads(row[0])
        if oversized:
            venue.submit.assert_not_called()
            assert order["stage"] == "REJECTED" and order["calculation"]["final_amount"] == 0
        else:
            venue.submit.assert_called_once()
            assert order["calculation"]["final_amount"] < 40
            assert order["stage"] == "SUBMITTED"
    finally:
        rt.db.db.close()
