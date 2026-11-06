import copy
import threading
import time
from unittest.mock import Mock,patch
import ccxt
import pytest
from pydantic import ValidationError
from market.admission import admit,query_for,before_fill,executable,ScannerConfig
from market.discovery import evaluate,Discovery,DiscoveryQuery
from terminal.config import Session
from terminal.runtime import Runtime
from execution.paper_queue import queue,drain
from test_discovery import fixture,NOW


def state():
    c=Session(consent=True,source="public",market_mode="dynamic",capital=1000,target=50,
        concentration=100,utilization=90,risk_per_trade_pct=20,cooldown=0,slots=1).settings()
    return dict(config=c,cash=1000,positions={},t=NOW,last_buy=0,id=1,revision=0)


def report(s):
    client,ticks=fixture(symbols=("NEW","BTC"))
    return evaluate(client,client.markets,ticks,query_for(s),NOW)


def test_real_budget_source_rules_and_liquidity_control_dynamic_entries():
    s=state();r=report(s);pool=admit(r,s,NOW)
    assert set(pool["entries"])=={"NEW","BTC"} and pool["execution_enabled"]
    s["cash"]=1
    assert not admit(r,s,NOW)["entries"]
    s=state();s["config"]["scanner"]["blacklist"]=["NEW/USDT"]
    assert admit(r,s,NOW,["NEW"])["monitor"]==["NEW","BTC"]
    assert admit(r,s,NOW)["entries"]==["BTC"]


@pytest.mark.parametrize("mutation",["platform","stale","future","spread","volume","change","precision","minimum","missing_limits","ineligible","missing_stamp"])
def test_tampered_or_stale_discovery_never_admits_new_positions(mutation):
    s=state();r=report(s);r["rows"]=r["rows"][:1];row=r["rows"][0]
    if mutation=="platform":r["exchange"]="binance"
    if mutation=="stale":row["source_timestamp"]=NOW-120
    if mutation=="future":row["source_timestamp"]=NOW+1
    if mutation=="spread":row["ask"]=110
    if mutation=="volume":row["quote_volume"]=1
    if mutation=="change":row["change_pct"]=100
    if mutation=="precision":row["rules"]["quantity_precision"]=0
    if mutation=="minimum":row["rules"]["limits"]["cost"]["min"]=10000
    if mutation=="missing_limits":row["rules"].pop("limits")
    if mutation=="ineligible":row["eligible"]=False
    if mutation=="missing_stamp":row["source_timestamp"]=None
    result=admit(r,s,NOW,["HELD"])
    assert not result["entries"] and result["monitor"]==["HELD"]


@pytest.mark.parametrize("change",[dict(execution="demo"),dict(source="history"),dict(product="swap"),dict(paper_rules="venue")])
def test_dynamic_config_cannot_expand_execution_authority(change):
    options=dict(consent=True,source="public",market_mode="dynamic")
    options.update(change)
    with pytest.raises(ValidationError):Session(**options)


def test_actual_fill_budget_is_rounded_and_rechecked_against_exchange_minimum():
    s=state();r=report(s);row=r["rows"][0];k=row["symbol"][:-5]
    s["discovery_report"]=r;s["dynamic_rules"]={k:dict(rule=row["rules"],checked_at=NOW,exchange="okx",product="spot")}
    m=dict(price=100,slip=.001)
    result=before_fill(s,k,m,10,"BUY")
    assert result["notional"]<=10 and result["notional"]>=5
    with pytest.raises(ValueError,match="最小数量或金额|限额"):before_fill(s,k,m,1,"BUY")
    with pytest.raises(ValueError,match="滑点"):before_fill(s,k,dict(m,slip=.01),10,"BUY")
    s["dynamic_rules"][k]["exchange"]="binance"
    with pytest.raises(ValueError,match="其他平台"):before_fill(s,k,m,10,"BUY")


def test_sell_does_not_need_entry_membership_but_requires_valid_platform_rules():
    s=state();row=report(s)["rows"][0];k=row["symbol"][:-5]
    s["positions"][k]=dict(qty=.1,cost=10,price=100,opened=NOW)
    s["dynamic_rules"]={k:dict(rule=row["rules"],checked_at=NOW,exchange="okx",product="spot")}
    result=before_fill(s,k,dict(price=100,slip=.001),0,"SELL")
    assert result["quantity"]==.1
    s["dynamic_rules"][k]["checked_at"]=NOW-120
    with pytest.raises(ValueError,match="有效交易规则"):before_fill(s,k,dict(price=100,slip=.001),0,"SELL")


def test_decimal_places_and_no_silent_sell_dust():
    s=state();rule=report(s)["rows"][0]["rules"];rule["precision_mode"]=ccxt.DECIMAL_PLACES
    rule.update(quantity_precision=3,price_precision=2)
    assert executable(rule,rule["symbol"],100,10,.001,1)["quantity"]==.099
    with pytest.raises(ValueError,match="残余"):executable(rule,rule["symbol"],100,0,.001,1,quantity=.1001)


def test_discovery_shutdown_does_not_wait_for_request_and_cleans_up_on_return():
    c,_=fixture();entered,release=threading.Event(),threading.Event();d=Discovery(lambda _:c,clock=lambda:NOW)
    fetch=c.fetch_tickers.side_effect
    ticks=c.fetch_tickers.return_value
    def slow(*a,**k):entered.set();assert release.wait(2);return ticks
    c.fetch_tickers.side_effect=slow;errors=[]
    def run():
        try:d.run(DiscoveryQuery())
        except Exception as err:errors.append(err)
    thread=threading.Thread(target=run);thread.start()
    try:
        assert entered.wait(1);start=time.monotonic();d.close(wait=False)
        assert time.monotonic()-start<.2
    finally:release.set();thread.join(2)
    assert not errors and not d.cache;c.close.assert_called_once()
    with pytest.raises(ValueError,match="关闭"):d.run(DiscoveryQuery())


@pytest.mark.parametrize("invalid",[dict(limit=0),dict(limit=201),dict(limit=True),dict(max_spread_pct=0),dict(max_slippage_pct=100),dict(whitelist=["BTC/USDC"])])
def test_scanner_execution_constraints_are_validated(invalid):
    with pytest.raises(ValidationError):ScannerConfig(**invalid)


@pytest.mark.parametrize("valid",[False,True])
def test_session_close_settlement_cannot_bypass_dynamic_rule_validation(tmp_path,valid):
    from challenge.manager import finish
    from execution.market_rules import spot_rules
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True,source="public",market_mode="dynamic",settlement="close"))
            s["positions"]["NEW"]=dict(qty=.1,price=100,entry=100,high=100,cost=10,opened=s["t"])
            s["cash"]-=10;s["feed_valid"]=True
            s["radar"]=[dict(symbol="NEW",time=s["t"],price=100,slip=.001,score=50)]
            if valid:
                c,_=fixture(symbols=("NEW",));m=c.markets["NEW/USDT"]
                s["dynamic_rules"]={"NEW":dict(rule=dict(spot_rules(m,c.precisionMode,m["symbol"]),limits=m["limits"]),checked_at=s["t"],exchange="okx",product="spot")}
            finish(rt.db,s)
            assert bool(rt.db.entries("fills",s["id"]))==valid
            assert bool(s["positions"])!=valid and s["pending"]!=valid
    finally:rt.shutdown();rt.db.db.close()
