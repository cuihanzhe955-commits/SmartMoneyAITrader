import copy
import time
from unittest.mock import Mock,patch
import ccxt
import pytest
from market.pool import plan,from_discovery
from market.feeds import START,historical,SYMBOLS
from execution.venue import Venue,MarketBatch
from terminal.runtime import Runtime
from terminal.config import Session
from challenge.manager import scan


def test_required_symbols_survive_candidate_removal_blacklist_and_deduplication():
    r=plan(["ETH","BTC","ETH"],["NEW","BTC"],["OLD","NEW"],["NEW","BTC"])
    assert r["entries"]==["ETH"] and r["monitor"]==["NEW","BTC","OLD","ETH"]
    assert r["retained"]["NEW"]==["持仓","在途委托"] and r["monitor_count"]==4


@pytest.mark.parametrize("bad",["BTC/USDT","btc","BTC:USDT","",None,True])
def test_invalid_monitor_identity_fails_instead_of_dropping_holdings(bad):
    with pytest.raises(ValueError):plan(["BTC"],[bad])


def report(stamp=START,exchange="okx"):
    return dict(exchange=exchange,read_only=True,changes_sessions=False,rows=[dict(symbol="NEW/USDT",eligible=True,source_timestamp=stamp)])


@pytest.mark.parametrize("stamp",[START-121,START+1,float("nan"),None,True])
def test_stale_or_unverifiable_discovery_never_admits_entries_but_keeps_holdings(stamp):
    r=from_discovery(report(stamp),"okx",START,["HELD"],["ORDER"])
    assert not r["entries"] and r["monitor"]==["HELD","ORDER"] and not r["execution_enabled"]


def test_wrong_exchange_report_does_not_move_account_or_forget_positions():
    r=from_discovery(report(exchange="gate"),"okx",START,["HELD"])
    assert r["admission"]=="invalid_report" and r["monitor"]==["HELD"]
    assert from_discovery(report(),"okx",START)["entries"]==["NEW"]


def wire(symbols=("BTC","ETH","NEW")):
    v=Venue.__new__(Venue);v.name="okx";v.env="public";v.swap=False;v.client=Mock()
    v.client.markets={s+"/USDT":{} for s in symbols}
    v.client.fetch_ohlcv=Mock(return_value=[[(START-60)*1000,100,101,99,100,2]])
    return v


def test_required_pair_outside_legacy_eight_is_fetched_first():
    v=wire();r=v.bars(["BTC","ETH"],required=["NEW"])
    assert list(r)==["NEW","BTC","ETH"] and not r.errors
    assert v.client.fetch_ohlcv.call_args_list[0].args[0]=="NEW/USDT"


def test_candidate_failure_does_not_discard_successful_required_candles():
    v=wire();v.client.fetch_ohlcv.side_effect=[[[ (START-60)*1000,100,101,99,100,2]],ccxt.RequestTimeout("fixture")]
    r=v.bars(["BTC"],required=["NEW"])
    assert list(r)==["NEW"] and "BTC" in r.errors and "NEW" not in r.errors


@pytest.mark.parametrize("failure",["missing","timeout","empty"])
def test_required_pair_failure_is_explicit_and_does_not_reuse_old_price(failure):
    v=wire(symbols=("BTC",) if failure=="missing" else ("BTC","NEW"))
    if failure=="timeout":v.client.fetch_ohlcv.side_effect=ccxt.RequestTimeout("fixture")
    if failure=="empty":v.client.fetch_ohlcv.return_value=[]
    with pytest.raises(ValueError,match="持仓或在途委托"):v.bars(["BTC"],required=["NEW"])


def test_rate_limit_stops_further_candidate_requests_without_retry():
    v=wire();v.client.fetch_ohlcv.side_effect=[[[ (START-60)*1000,100,101,99,100,2]],ccxt.RateLimitExceeded("fixture")]
    r=v.bars(["BTC","ETH"],required=["NEW"])
    assert list(r)==["NEW"] and v.client.fetch_ohlcv.call_count==2
    assert r.errors["ETH"]=="本轮限频，尚未请求"


@pytest.mark.parametrize("error",[ccxt.PermissionDenied("denied"),ccxt.ExchangeNotAvailable("HTTP 451 restricted location")])
def test_region_or_permission_refusal_is_not_treated_as_optional_candidate_failure(error):
    v=wire();v.client.fetch_ohlcv.side_effect=error
    with pytest.raises(type(error)):v.bars(["BTC","ETH"])
    assert v.client.fetch_ohlcv.call_count==1


def enrich(rows,m,c):
    m.update(score=100 if m["price"]>10000 else 80,buy=True,signals=["测试"],trend=0,momentum=0)


def test_only_allowed_candidates_consume_rank_slots(tmp_path):
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True,candidates=1,slots=1,cooldown=0))
            with patch("strategy.ensemble.enrich",side_effect=enrich),patch("challenge.manager.execute") as execute:
                scan(rt.db,s,START,{k:v for k,v in historical(START).items() if k in ("BTC","ETH")},entry_symbols=["ETH"])
                assert [c.args[2] for c in execute.call_args_list]==["ETH"]
    finally:rt.shutdown();rt.db.db.close()


def test_no_new_entry_does_not_disable_protective_exit(tmp_path):
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True));rows=historical(START)["BTC"];price=rows[-1][4]
            s["positions"]["NEW"]=dict(qty=.001,price=price,entry=price*1.1,high=price*1.1,cost=price*.001,opened=START)
            with patch("strategy.ensemble.enrich",side_effect=enrich),patch("challenge.manager.execute") as execute:
                scan(rt.db,s,START,{"NEW":rows},entry_symbols=[])
                assert execute.call_args.args[2:4]==("NEW","SELL")
                assert execute.call_args.args[-1]=="固定止损"
    finally:rt.shutdown();rt.db.db.close()


def test_removed_candidate_cancels_paper_buy_before_it_can_fill(tmp_path):
    from execution.paper_queue import queue
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True));rows=historical(START)["BTC"]
            queue(rt.db,s,"BTC","BUY",{"price":rows[-1][4],"time":START-60},10,"fixture")
            scan(rt.db,s,START,{"BTC":rows},entry_symbols=[])
            assert not s["paper_pending"] and not rt.db.entries("fills",s["id"])
            assert any("退出入场候选池" in e["summary"] for e in rt.db.entries("system_events",s["id"]))
    finally:rt.shutdown();rt.db.db.close()


def test_public_runtime_persists_monitor_scope_and_recovers_from_positions(tmp_path):
    now=int(time.time());rows=historical(START)["BTC"];price=rows[-1][4]
    native=[[(r[0]+now-START-60)*1000,r[1],r[2],r[3],r[4],r[5]/r[4]] for r in rows]
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True,source="public",strict_min=999999))
            s["positions"]["NEW"]=dict(qty=.001,price=price,entry=price,high=price,cost=price*.001,opened=now)
            s["cash"]-=price*.001;rt.db.save(s);rt.command(s["id"],"start")
        v=wire(("BTC","NEW"));v.client.fetch_ohlcv.return_value=native;rt.venue=Mock(return_value=v)
        with patch("strategy.ensemble.enrich",side_effect=lambda rows,m,c:m.update(buy=False,trend=0,momentum=0)):
            rt.tick()
        saved=rt.db.load();assert saved["scan_pool"]["required"]==["NEW"]
        assert saved["scan_pool"]["fetched_count"]==2 and "ETH" in saved["scan_pool"]["errors"]
        assert saved["scan_pool"]["valid_count"]==2
        assert "NEW" in saved["positions"] and "NEW" not in saved["scan_pool"]["entries"]
        assert "_monitor_pool" not in saved["config"]
    finally:rt.shutdown();rt.db.db.close()
    restarted=Runtime(tmp_path)
    try:
        state=restarted.db.load();restored=plan(SYMBOLS,state["positions"],state.get("paper_pending",{}))
        assert restored["required"]==["NEW"]
    finally:restarted.shutdown();restarted.db.db.close()
