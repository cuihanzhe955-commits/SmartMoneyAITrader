from decimal import Decimal
import pytest
from market.event_units import unit_evidence, precision_envelope
from market.event_costs import CostQuery, curve_parameters, estimate_cost, CLOB_INFO
from market.event_details import BOOK
from test_event_costs import metadata, info, depth, service
from test_event_research import NOW


@pytest.mark.parametrize("fee,low,high",[
    ("0", "0", "0"), ("0.000009999", "0", "0"),
    ("0.00001", "0.00001", "0.00001"),
    ("0.000014999", "0.00001", "0.00002"),
    ("0.000015", "0.00001", "0.00002"),
    ("1.75123456", "1.75123", "1.75124"),
])
def test_documented_precision_without_inventing_a_rounding_direction(fee, low, high):
    assert precision_envelope(Decimal(fee)) == (Decimal(low), Decimal(high))


def test_negative_fee_cannot_be_accepted():
    with pytest.raises(ValueError):
        precision_envelope(Decimal("-0.01"))


@pytest.mark.parametrize("field,value",[
    ("minimum_size", None), ("minimum_size", 0), ("minimum_size", 6),
    ("minimum_size", True), ("minimum_size", float("nan")),
    ("price_tick", None), ("price_tick", .005),
])
def test_missing_or_disagreeing_gamma_rules_do_not_silently_pass(field, value):
    m = metadata(); m[field] = value
    with pytest.raises(ValueError):
        estimate_cost(CostQuery(market_id="1"), m, info(), depth(), NOW)


def test_units_are_source_scoped_and_do_not_grant_execution():
    m = metadata(); result = unit_evidence(m, curve_parameters(info(), m))
    assert result["gamma_minimum_unit"] == "USDC"
    assert result["gamma_minimum_notional"] == 5
    assert result["native_clob_minimum_unit"] is None
    assert result["collateral_asset"] is None
    for field in ("native_unit_verified", "collateral_asset_verified", "fee_rounding_direction_verified",
                  "fee_match_aggregation_verified", "simulation_ready", "execution_enabled"):
        assert result[field] is False
    assert len(result["blockers"]) == 3


def test_precision_scenario_is_per_level_and_never_replaces_budget_reserve():
    raw = depth(); raw["asks"] = [dict(price=".50", size="10.123456"), dict(price=".51", size="50")]
    r = estimate_cost(CostQuery(market_id="1", shares=20, budget=20, max_slippage_pct=3), metadata(), info(), raw, NOW)
    assert r["modeled_level_count"] == 2
    assert r["precision_scenario_low"] <= r["modeled_fee"] <= r["precision_scenario_high"]
    assert r["rounding_reserve"] == .0002
    assert r["modeled_total"] == pytest.approx(r["modeled_gross"] + r["modeled_fee"] + .0002)
    assert r["modeled_total"] <= r["requested_budget"]
    assert "not a bound on actual" in r["precision_scenario"]


def test_sub_quantum_model_fee_is_not_silently_removed_from_the_budget():
    raw = depth(); raw["asks"] = [dict(price=".50", size=".0001")]
    r = estimate_cost(CostQuery(market_id="1", shares=.0001, budget=1), metadata(), info(), raw, NOW)
    assert 0 < r["modeled_fee"] < .00001
    assert r["precision_scenario_low"] == r["precision_scenario_high"] == 0
    assert r["rounding_reserve"] == .0001
    assert r["modeled_total"] > r["modeled_gross"]


def test_gamma_conflict_stops_before_book_and_does_not_poison_cache():
    d = service(); original = d.fetch.side_effect
    def conflict(url, params):
        result = original(url, params)
        if url.startswith(CLOB_INFO): result["mos"] = 6
        return result
    d.fetch.side_effect = conflict
    with pytest.raises(ValueError, match="不一致"):
        d.cost(CostQuery(market_id="1"))
    assert BOOK not in [c.args[0] for c in d.fetch.call_args_list]
    assert not d.cache["cost"]
    d.fetch.side_effect = original
    assert d.cost(CostQuery(market_id="1"))["unit_evidence"]["gamma_minimum_unit"] == "USDC"
