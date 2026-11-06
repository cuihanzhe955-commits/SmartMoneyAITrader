import copy,threading,time
from unittest.mock import Mock,patch
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from market.predictions import normalize,public_get,ENDPOINT
from market.event_details import EventDetails,MarketSelector,QuoteQuery,book_snapshot,resolution_evidence,BOOK,FEE,RESOLUTION
from terminal.api import create_app
from test_event_research import market,NOW


def metadata():return normalize(market(),NOW)


def book():
    return dict(market=metadata()["condition_id"],asset_id="2",timestamp=str(NOW*1000),hash="a"*40,
        bids=[dict(price=".40",size="100"),dict(price=".45",size="20")],
        asks=[dict(price=".50",size="30"),dict(price=".48",size="40")],min_order_size="5",tick_size=".01")


def resolved(status="resolved"):
    return dict(data=[dict(condition_id=metadata()["condition_id"],status=status,
        payouts=[1000000,0],resolved_at=str(NOW-10),last_update_timestamp=str(NOW-5))])


def service(book_data=None,resolution=None,fee=None):
    def fetch(url,params):
        if url==ENDPOINT+"/1":return market()
        if url==BOOK:return book() if book_data is None else book_data
        if url==FEE:return dict(base_fee=30) if fee is None else fee
        if url==RESOLUTION:return resolved() if resolution is None else resolution
        raise AssertionError("Unexpected endpoint")
    return EventDetails(fetch=Mock(side_effect=fetch),clock=lambda:NOW)


def test_quote_normalizes_depth_binds_token_and_preserves_fee_model_unknown():
    d=service();q=d.quote(QuoteQuery(market_id="1"))
    assert q["best_bid"]==.45 and q["best_ask"]==.48 and q["spread"]==.03
    assert q["source_timestamp"]==NOW and q["base_fee_bps"]==30 and q["base_fee_verified"]
    assert not q["fee_model_verified"] and not q["simulation_ready"] and not q["execution_enabled"]
    assert q["book_hash"]=="a"*40 and q["read_only"]
    assert [c.args[0] for c in d.fetch.call_args_list]==[ENDPOINT+"/1",BOOK,FEE]


@pytest.mark.parametrize("field,value",[("market","0x"+"f"*64),("asset_id","3"),("timestamp",str((NOW-30)*1000)),
    ("timestamp",str((NOW+1)*1000)),("timestamp",None),("timestamp","NaN"),("hash",None),
    ("tick_size","0"),("min_order_size","-1"),("bids",None),
    ("bids",[dict(price=".60",size="1")]),("asks",[dict(price="NaN",size="1")]),
    ("asks",[dict(price=".485",size="1")]),("asks",[dict(price=".50",size="0")]),
    ("asks",[dict(price=".50",size="1"),dict(price=".50",size="2")])])
def test_bad_book_cannot_be_accepted_as_fresh_quote(field,value):
    raw=book();raw[field]=value
    with pytest.raises(ValueError):book_snapshot(raw,metadata(),"2",NOW)


def test_one_sided_book_is_reported_without_manufacturing_a_price():
    raw=book();raw["asks"]=[];q=service(raw).quote(QuoteQuery(market_id="1"))
    assert not q["quote_available"] and q["best_ask"] is None and q["spread"] is None


@pytest.mark.parametrize("fee",[{},dict(base_fee=True),dict(base_fee=-1),dict(base_fee="30"),dict(base_fee=10001)])
def test_missing_or_invalid_fee_is_not_assumed_zero(fee):
    with pytest.raises(ValueError,match="费率"):service(fee=fee).quote(QuoteQuery(market_id="1"))


def test_zero_fee_is_valid_explicit_evidence_not_a_default():
    assert service(fee=dict(base_fee=0)).quote(QuoteQuery(market_id="1"))["base_fee_bps"]==0


def test_second_outcome_cannot_reuse_first_outcome_book():
    with pytest.raises(ValueError,match="Token"):service().quote(QuoteQuery(market_id="1",outcome_index=1))


def test_resolution_final_result_maps_payouts_to_tokens_without_changing_assets():
    r=service().resolution(MarketSelector(market_id="1"))
    assert r["settlement_verified"] and not r["onchain_verified"] and r["settlement_asset"] is None
    assert r["payouts"]==[dict(outcome="Up",token_id="2",payout=1.),dict(outcome="Down",token_id="3",payout=0.)]
    assert not r["execution_enabled"]


@pytest.mark.parametrize("status",["proposed","disputed","pending","unknown_new_status","unresolved"])
def test_nonfinal_status_cannot_infer_a_winner_from_payout_like_fields(status):
    r=resolution_evidence(resolved(status),metadata(),NOW)
    assert not r["settlement_verified"] and r["payouts"] is None


def test_empty_official_record_is_not_a_refund_or_zero_payout():
    r=resolution_evidence(dict(data=[]),metadata(),NOW)
    assert r["status"]=="NOT_AVAILABLE" and r["payouts"] is None and not r["settlement_verified"]


@pytest.mark.parametrize("change",["wrong_condition","missing_condition","duplicate","not_list","sum","negative","nan"])
def test_unverifiable_settlement_is_rejected(change):
    raw=resolved();row=raw["data"][0]
    if change=="wrong_condition":row["condition_id"]="0x"+"f"*64
    if change=="missing_condition":row["condition_id"]=None
    if change=="duplicate":raw["data"].append(copy.deepcopy(row))
    if change=="not_list":raw["data"]={}
    if change=="sum":row["payouts"]=[1,1]
    if change=="negative":row["payouts"]=[-1,2]
    if change=="nan":row["payouts"]=[float("nan"),0]
    with pytest.raises(ValueError):resolution_evidence(raw,metadata(),NOW)


@pytest.mark.parametrize("change",["missing_payouts","missing_time","future_time"])
def test_reported_resolved_without_complete_evidence_is_not_verified(change):
    raw=resolved();row=raw["data"][0]
    if change=="missing_payouts":row.pop("payouts")
    if change=="missing_time":row.pop("resolved_at")
    if change=="future_time":row["resolved_at"]=str(NOW+1)
    r=resolution_evidence(raw,metadata(),NOW)
    assert not r["settlement_verified"] and r["payouts"] is None


def test_half_payout_is_preserved_as_official_vector_not_forced_to_yes_or_no():
    raw=resolved();raw["data"][0]["payouts"]=[500000,500000]
    r=resolution_evidence(raw,metadata(),NOW)
    assert r["settlement_verified"] and [x["payout"] for x in r["payouts"]]==[.5,.5]


@pytest.mark.parametrize("fields",[dict(market_id="../orders"),dict(market_id=1),dict(market_id="0"),dict(market_id="1",outcome_index=True),dict(market_id="1",outcome_index=2),dict(market_id="1",key="fixture")])
def test_selector_does_not_accept_execution_urls_or_ambiguous_identity(fields):
    with pytest.raises(ValidationError):QuoteQuery(**fields)


def test_transport_rejects_wallet_and_private_or_custom_endpoints_before_network():
    with patch("market.predictions.requests.Session") as client:
        with pytest.raises(ValueError,match="未批准"):public_get("https://clob.polymarket.com/orders",{})
        client.assert_not_called()


def test_quote_cache_uses_source_age_and_returns_copy_without_retimestamping():
    now=[NOW];mono=[0];d=service();d.clock=lambda:now[0];d.monotonic=lambda:mono[0]
    first=d.quote(QuoteQuery(market_id="1"));first["bids"][0]["price"]=99
    mono[0]=1;now[0]+=1;again=d.quote(QuoteQuery(market_id="1"))
    assert again["cached"] and again["bids"][0]["price"]==.45 and again["source_timestamp"]==NOW
    assert d.fetch.call_count==3
    now[0]+=30
    with pytest.raises(ValueError,match="过期"):d.quote(QuoteQuery(market_id="1"))


def test_resolution_and_quote_lanes_are_independent_and_close_never_waits():
    d=service();original=d.fetch.side_effect;entered,release=threading.Event(),threading.Event();errors=[]
    def slow(url,params):
        if url==BOOK:entered.set();assert release.wait(3)
        return original(url,params)
    d.fetch.side_effect=slow
    def run():
        try:d.quote(QuoteQuery(market_id="1"))
        except ValueError as e:errors.append(str(e))
    t=threading.Thread(target=run);t.start()
    try:
        assert entered.wait(1)
        assert d.resolution(MarketSelector(market_id="1"))["settlement_verified"]
        with pytest.raises(ValueError,match="正在查询"):d.quote(QuoteQuery(market_id="1"))
        start=time.monotonic();d.close();assert time.monotonic()-start<.2
    finally:release.set();t.join(2)
    assert errors and all(not x for x in d.cache.values())


def test_research_endpoints_do_not_touch_sessions_or_order_ledgers(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as c:
        app.state.event_details=service()
        before=c.get("/api/state").json()
        assert c.post("/api/research/events/quote",json=dict(market_id="1")).status_code==200
        assert c.post("/api/research/events/resolution",json=dict(market_id="1")).json()["settlement_verified"]
        assert c.get("/api/state").json()==before
        assert c.post("/api/research/events/quote",json=dict(market_id="1",execution="live")).status_code==422


def test_closed_market_can_be_resolved_by_exact_id_without_open_list_filters():
    d=service();original=d.fetch.side_effect
    def fetch(url,params):
        if url==ENDPOINT+"/1":
            assert params=={}
            data=market();data.update(closed=True,acceptingOrders=False)
            return data
        return original(url,params)
    d.fetch.side_effect=fetch
    assert d.resolution(MarketSelector(market_id="1"))["settlement_verified"]
    with pytest.raises(ValueError,match="开放"):d.quote(QuoteQuery(market_id="1"))


@pytest.mark.parametrize("suffix",["../orders","1?redirect=https://fixture.invalid","01","1/positions"])
def test_exact_market_route_allowlist_cannot_reach_other_paths(suffix):
    with patch("market.predictions.requests.Session") as factory:
        with pytest.raises(ValueError,match="未批准"):public_get(ENDPOINT+"/"+suffix,{})
        factory.assert_not_called()


@pytest.mark.parametrize("values",[[1,0],[1.0,999999],[True,999999],["1000000",0],[0,1000001]])
def test_resolution_does_not_guess_scaled_or_float_payout_units(values):
    raw=resolved();raw["data"][0]["payouts"]=values
    with pytest.raises(ValueError,match="micro-USDC"):resolution_evidence(raw,metadata(),NOW)


def test_documented_micro_usdc_vector_is_retained_with_normalized_per_share_value():
    r=resolution_evidence(resolved(),metadata(),NOW)
    assert r["payout_source_unit"]=="micro-USDC/share" and r["raw_payouts_micro_usdc"]==[1000000,0]
    assert r["payouts"][0]["payout"]==1


@pytest.mark.parametrize("value",["1e309","1e-999",".123456789012345678901"])
def test_extreme_numeric_fields_return_a_clear_rejection(value):
    raw=book();raw["bids"][0]["size"]=value
    with pytest.raises(ValueError):book_snapshot(raw,metadata(),"2",NOW)
