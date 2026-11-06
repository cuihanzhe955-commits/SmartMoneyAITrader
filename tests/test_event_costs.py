import copy
from decimal import Decimal
from unittest.mock import Mock,patch
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from market.event_costs import CostQuery,estimate_cost,curve_parameters,CLOB_INFO
from market.event_details import EventDetails,BOOK
from market.predictions import normalize,public_get,ENDPOINT
from test_event_research import market,NOW
from test_event_details import book
from terminal.api import create_app


def metadata():
    raw=market();raw.update(version="v1",feesEnabled=True)
    return normalize(raw,NOW)


def info(rate=.07):
    return dict(t=[dict(t="2",o="Up"),dict(t="3",o="Down")],fd=dict(r=rate,e=1,to=True),mos=5,mts=.01,mbf=1000,tbf=1000)


def depth():
    raw=book();raw.update(bids=[dict(price=".49",size="500")],asks=[dict(price=".50",size="500")])
    return raw


def service():
    def fetch(url,params):
        if url==ENDPOINT+"/1":
            raw=market();raw.update(version="v1",feesEnabled=True);return raw
        if url==CLOB_INFO+metadata()["condition_id"]:return info()
        if url==BOOK:return depth()
        raise AssertionError(url)
    return EventDetails(fetch=Mock(side_effect=fetch),clock=lambda:NOW)


def test_official_exponent_one_example_is_used_instead_of_base_bps():
    q=CostQuery(market_id="1",shares=100,budget=100)
    r=estimate_cost(q,metadata(),info(),depth(),NOW)
    assert r["modeled_gross"]==50 and r["modeled_fee"]==1.75
    assert r["rounding_reserve"]==.0001 and r["modeled_total"]==50+1.75+.0001
    assert r["research_feasible"] and r["complete_fill_model"]
    assert r["fee_curve_verified"] and not r["transaction_fee_verified"] and not r["collateral_asset_verified"]
    assert not r["simulation_ready"] and not r["execution_enabled"]


def test_depth_weighted_cost_and_slippage_are_recomputed_per_level():
    raw=depth();raw["asks"]=[dict(price=".51",size="50"),dict(price=".50",size="10")]
    q=CostQuery(market_id="1",shares=20,budget=100,max_slippage_pct=3)
    r=estimate_cost(q,metadata(),info(),raw,NOW)
    assert r["modeled_gross"]==10.1 and r["average_price"]==.505
    assert r["modeled_fee"]==pytest.approx(10*.07*.5*.5+10*.07*.51*.49)
    assert r["modeled_slippage_pct"]==pytest.approx(1)
    assert len(r["depth_fills"])==2


def test_budget_reduces_quantity_including_fee_and_rounding_reserve():
    r=estimate_cost(CostQuery(market_id="1",shares=100,budget=10),metadata(),info(),depth(),NOW)
    assert r["modeled_total"]<=10 and 0<r["modeled_shares"]<20
    assert not r["complete_fill_model"] and "研究预算限制" in r["limits"]
    assert r["remaining_budget"]>=0


def test_slippage_bound_does_not_fill_more_expensive_depth():
    raw=depth();raw["asks"]=[dict(price=".50",size="10"),dict(price=".60",size="100")]
    r=estimate_cost(CostQuery(market_id="1",shares=20,budget=100,max_slippage_pct=0),metadata(),info(),raw,NOW)
    assert r["modeled_shares"]==10 and "价格超出滑点上限" in r["limits"]


def test_insufficient_depth_and_conservative_minimum_are_explicit():
    raw=depth();raw["asks"]=[dict(price=".50",size="2")]
    r=estimate_cost(CostQuery(market_id="1",shares=10,budget=100),metadata(),info(),raw,NOW)
    assert not r["research_feasible"] and not r["complete_fill_model"]
    assert "保守最小份额检查未通过" in r["limits"] and "保守最小名义金额检查未通过" in r["limits"]


@pytest.mark.parametrize("field,value",[("version",None),("version","v2"),("feesEnabled",None)])
def test_unsupported_version_or_unknown_fee_switch_is_not_guessed(field,value):
    raw=market();raw.update(version="v1",feesEnabled=True);raw[field]=value
    with pytest.raises(ValueError):estimate_cost(CostQuery(market_id="1"),normalize(raw,NOW),info(),depth(),NOW)


@pytest.mark.parametrize("mutation",["token","label","duplicates","missing_curve","exponent","non_taker","nan","rule_mismatch","disabled_conflict"])
def test_curve_identity_formula_and_rules_cannot_be_bypassed(mutation):
    data=info();m=metadata()
    if mutation=="token":data["t"][0]["t"]="999"
    if mutation=="label":data["t"][0]["o"]="Other"
    if mutation=="duplicates":data["t"][1]=data["t"][0]
    if mutation=="missing_curve":data.pop("fd")
    if mutation=="exponent":data["fd"]["e"]=2
    if mutation=="non_taker":data["fd"]["to"]=False
    if mutation=="nan":data["fd"]["r"]=float("nan")
    if mutation=="rule_mismatch":data["mts"]=.001
    if mutation=="disabled_conflict":m["fees_enabled"]=False
    with pytest.raises(ValueError):estimate_cost(CostQuery(market_id="1"),m,data,depth(),NOW)


def test_confirmed_zero_curve_does_not_invent_fee_or_rounding_charge():
    m=metadata();m["fees_enabled"]=False
    r=estimate_cost(CostQuery(market_id="1",shares=10,budget=10),m,info(0),depth(),NOW)
    assert r["modeled_fee"]==r["rounding_reserve"]==0


def test_quantity_rounding_is_explained_and_never_rounds_up():
    r=estimate_cost(CostQuery(market_id="1",shares=10.1234567,budget=20),metadata(),info(),depth(),NOW)
    assert r["rounded_requested_shares"]==10.123456 and not r["requested_goal_exact"]
    assert "目标份额按研究步长向下取整" in r["limits"]


@pytest.mark.parametrize("data",[dict(shares=0),dict(budget=-1),dict(max_slippage_pct=-1),dict(shares=True),dict(budget=float("inf")),dict(execution="live")])
def test_invalid_cost_inputs_cannot_enable_execution(data):
    with pytest.raises(ValidationError):CostQuery(market_id="1",**data)


def test_cost_service_uses_only_exact_metadata_curve_and_book_gets():
    d=service();r=d.cost(CostQuery(market_id="1",shares=20,budget=20))
    assert r["read_only"] and not r["changes_sessions"]
    assert [c.args[0] for c in d.fetch.call_args_list]==[ENDPOINT+"/1",CLOB_INFO+metadata()["condition_id"],BOOK]
    second=d.cost(CostQuery(market_id="1",shares=20,budget=20));assert second["cached"]
    assert d.fetch.call_count==3
    d.cost(CostQuery(market_id="1",shares=21,budget=20));assert d.fetch.call_count==6


def test_curve_endpoint_allowlist_excludes_user_or_order_paths():
    with patch("market.predictions.requests.Session") as factory:
        with pytest.raises(ValueError):public_get(CLOB_INFO+metadata()["condition_id"]+"/orders",{})
        factory.assert_not_called()


def test_cost_api_leaves_runtime_ledger_untouched(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as c:
        app.state.event_details=service();before=c.get("/api/state").json()
        r=c.post("/api/research/events/cost",json=dict(market_id="1",shares=20,budget=20))
        assert r.status_code==200 and not r.json()["execution_enabled"]
        assert c.get("/api/state").json()==before


def test_unsupported_curve_stops_before_candle_or_book_requests():
    d=service();original=d.fetch.side_effect
    def fetch(url,params):
        if url.startswith(CLOB_INFO):
            result=info();result["fd"]["e"]=2;return result
        return original(url,params)
    d.fetch.side_effect=fetch
    with pytest.raises(ValueError,match="范围"):d.cost(CostQuery(market_id="1"))
    assert BOOK not in [c.args[0] for c in d.fetch.call_args_list]


def test_research_depth_smaller_than_step_never_claims_budget_was_the_limit():
    raw=depth();raw["asks"]=[dict(price=".50",size="1.123456789"),dict(price=".51",size="10")]
    r=estimate_cost(CostQuery(market_id="1",shares=10,budget=100,max_slippage_pct=5),metadata(),info(),raw,NOW)
    assert r["modeled_shares"]==10 and "研究预算限制" not in r["limits"]


def test_unconfirmed_zero_curve_cannot_replace_missing_fee_switch():
    m=metadata();m["fees_enabled"]=None
    with pytest.raises(ValueError,match="开关"):estimate_cost(CostQuery(market_id="1"),m,info(0),depth(),NOW)


def test_rounding_does_not_hide_the_additional_depth_limit():
    raw=depth();raw["asks"]=[dict(price=".50",size="1")]
    r=estimate_cost(CostQuery(market_id="1",shares=10.1234567,budget=100),metadata(),info(),raw,NOW)
    assert "目标份额按研究步长向下取整" in r["limits"]
    assert "本次快照深度或研究数量步长限制" in r["limits"]


def test_cost_lane_rejects_stale_cached_data_instead_of_retimestamping():
    now=[NOW];mono=[0];d=service();d.clock=lambda:now[0];d.monotonic=lambda:mono[0]
    r=d.cost(CostQuery(market_id="1"));assert r["source_timestamp"]==NOW
    now[0]+=30;mono[0]=1
    with pytest.raises(ValueError,match="过期"):d.cost(CostQuery(market_id="1"))


def test_complete_replay_input_reproduces_more_than_twenty_modeled_levels():
    raw=depth();raw['asks']=[dict(price=str(Decimal('.50')+Decimal('.01')*i),size='10') for i in range(25)]
    q=CostQuery(market_id='1',shares=300,budget=1000,max_slippage_pct=100)
    first=estimate_cost(q,metadata(),info(),raw,NOW)
    assert first['depth_rows_truncated']
    source=first['replay_input']
    replay=estimate_cost(q,source['market'],source['info'],source['book'],first['received_at'])
    assert replay['modeled_total']==first['modeled_total'] and replay['modeled_shares']==first['modeled_shares']
    assert len(source['book']['asks'])==25
