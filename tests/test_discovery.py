import copy
import threading
import time
from unittest.mock import Mock
from urllib.parse import urlparse
import ccxt
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from market.discovery import Discovery,DiscoveryQuery,evaluate,public_client
from terminal.api import create_app

NOW=1722816000


def fixture(name="okx",symbols=("BTC","ETH","NEW")):
    c=getattr(ccxt,name)({"enableRateLimit":False});markets=[];tickers={}
    for i,base in enumerate(symbols):
        symbol=base+"/USDT"
        markets.append(dict(id=base+"USDT",symbol=symbol,base=base,quote="USDT",baseId=base,quoteId="USDT",
            type="spot",spot=True,swap=False,future=False,option=False,contract=False,active=True,linear=False,inverse=False,
            precision={"amount":.001,"price":.01},limits={"amount":{"min":.001},"price":{},"cost":{"min":5}}))
        tickers[symbol]=dict(symbol=symbol,timestamp=NOW*1000,bid=100,ask=100.1,last=100,open=99,
            high=105+i,low=95-i,percentage=1,quoteVolume=2_000_000)
    c.set_markets(markets);c.load_markets=Mock(return_value=c.markets);c.fetch_tickers=Mock(return_value=tickers)
    c.close=Mock();c.fetch=Mock(side_effect=AssertionError("network forbidden"))
    return c,tickers


def test_discovers_beyond_original_eight_and_preserves_cost_budget():
    c,t=fixture();r=evaluate(c,c.markets,t,DiscoveryQuery(),NOW)
    assert r["scope"]==3 and r["eligible"]==3
    assert r["rows"][0]["symbol"]=="NEW/USDT"
    for row in r["rows"]:
        assert row["budget"]["total"]<=10 and row["budget"]["notional"]>=5
    assert not r["executable"] and not r["changes_sessions"]
    c.fetch.assert_not_called()


@pytest.mark.parametrize("query,expected",[(dict(search="ETH"),["ETH/USDT"]),
    (dict(whitelist=["BTC","eth"],blacklist=["ETH"]),["BTC/USDT"]),
    (dict(limit=1),["NEW/USDT"])])
def test_search_allow_deny_and_visible_limit(query,expected):
    c,t=fixture();r=evaluate(c,c.markets,t,DiscoveryQuery(**query),NOW)
    assert [x["symbol"] for x in r["rows"]]==expected


@pytest.mark.parametrize("field,value,reason",[("timestamp",None,"时间"),("timestamp",(NOW-121)*1000,"时间"),
    ("timestamp",(NOW+3)*1000,"时间"),("quoteVolume",1,"成交额"),("ask",102,"价差"),
    ("percentage",60,"涨跌幅"),("bid",float("nan"),"盘口"),("high",None,"高低价")])
def test_invalid_or_filtered_ticker_has_explicit_reason(field,value,reason):
    c,t=fixture(symbols=("BTC",));t["BTC/USDT"][field]=value
    r=evaluate(c,c.markets,t,DiscoveryQuery(),NOW)
    assert r["eligible"]==0 and any(reason in s for s in r["rows"][0]["reasons"])


@pytest.mark.parametrize("change",["inactive","missing_min","invalid_precision","min_cost","max_cost","min_quantity"])
def test_same_execution_rules_block_unusable_market(change):
    c,t=fixture(symbols=("BTC",));m=c.markets["BTC/USDT"]
    if change=="inactive":m["active"]=False
    if change=="missing_min":m["limits"]["amount"]["min"]=None
    if change=="invalid_precision":m["precision"]=[]
    if change=="min_cost":m["limits"]["cost"]["min"]=11
    if change=="max_cost":m["limits"]["cost"]["max"]=5
    if change=="min_quantity":m["limits"]["amount"]["min"]=1
    r=evaluate(c,c.markets,t,DiscoveryQuery(),NOW)
    assert r["eligible"]==0 and r["rows"][0]["reasons"]


@pytest.mark.parametrize("bad",[dict(budget=0),dict(budget=float("inf")),dict(fee_pct=100),dict(whitelist=["BTC/USDC"]),dict(limit=True),dict(permissions="trade")])
def test_invalid_query_cannot_extend_permissions(bad):
    with pytest.raises(ValidationError):DiscoveryQuery(**bad)


def test_bulk_cache_and_rule_refresh_have_independent_ttls():
    c,t=fixture();clock=[NOW];factory=Mock(return_value=c)
    d=Discovery(factory,clock=lambda:clock[0],monotonic=lambda:clock[0])
    first=d.run(DiscoveryQuery());clock[0]+=30
    second=d.run(DiscoveryQuery(budget=6))
    assert not first["cached"] and second["cached"]
    assert second["rows"][0]["received_at"]==NOW and second["received_at"]==NOW
    assert c.fetch_tickers.call_count==1 and c.load_markets.call_count==1
    clock[0]+=31;d.run(DiscoveryQuery());assert c.fetch_tickers.call_count==2
    clock[0]+=540;d.run(DiscoveryQuery());assert c.load_markets.call_count==2
    c.fetch_tickers.assert_called_with(params={"type":"spot"})
    d.close()


@pytest.mark.parametrize("error",[ccxt.RequestTimeout,ccxt.RateLimitExceeded,ccxt.ExchangeNotAvailable])
def test_failure_does_not_return_old_cached_success_or_retry(error):
    c,t=fixture();clock=[NOW];d=Discovery(lambda _:c,clock=lambda:clock[0],monotonic=lambda:clock[0])
    d.run(DiscoveryQuery());clock[0]+=61;c.fetch_tickers.side_effect=error("fixture")
    with pytest.raises(ValueError):d.run(DiscoveryQuery())
    assert c.fetch_tickers.call_count==2


def test_no_parallel_duplicate_bulk_request():
    c,t=fixture();entered=threading.Event();release=threading.Event()
    def blocked(**kwargs):entered.set();assert release.wait(5);return t
    c.fetch_tickers.side_effect=blocked;d=Discovery(lambda _:c,clock=lambda:NOW)
    future=threading.Thread(target=lambda:d.run(DiscoveryQuery()));future.start();assert entered.wait(5)
    try:
        with pytest.raises(ValueError,match="正在进行"):d.run(DiscoveryQuery())
    finally:release.set();future.join(5)
    assert c.fetch_tickers.call_count==1


def test_api_research_cannot_create_or_change_sessions(tmp_path):
    app=create_app(tmp_path);c,t=fixture()
    with TestClient(app) as api:
        app.state.discovery.factory=lambda _:c;app.state.discovery.clock=lambda:NOW
        assert api.post("/api/sessions",json={"consent":True}).status_code==200
        before=api.get("/api/state").json()
        r=api.post("/api/research/markets",json={"budget":10})
        assert r.status_code==200 and r.json()["eligible"]==3
        after=api.get("/api/state").json()
        assert after["state"]==before["state"] and after["fills"]==before["fills"]
        assert api.post("/api/research/markets",json={"budget":10,"execution":"live"}).status_code==422


@pytest.mark.parametrize("name",["okx","binance","gate"])
def test_native_spot_market_discovery_uses_bounded_public_metadata_requests(name):
    c=public_client(name);c.enableRateLimit=False;paths=[]
    def fetch(url,method,headers,body):
        path=urlparse(url).path;paths.append(path);assert method=="GET";assert not c.apiKey
        if path=="/api/v4/margin/currency_pairs":return []
        if name=="okx":return {"code":"0","data":[dict(instType="SPOT",instId="NEW-USDT",baseCcy="NEW",quoteCcy="USDT",state="live",lotSz=".001",minSz=".001",tickSz=".01")]}
        if name=="binance":return {"symbols":[dict(symbol="NEWUSDT",baseAsset="NEW",quoteAsset="USDT",status="TRADING",isSpotTradingAllowed=True,permissions=["SPOT"],filters=[
            {"filterType":"LOT_SIZE","minQty":".001","maxQty":"1000000","stepSize":".001"},
            {"filterType":"PRICE_FILTER","minPrice":".01","maxPrice":"1000000","tickSize":".01"},
            {"filterType":"MIN_NOTIONAL","minNotional":"5"}])]}
        return [dict(id="NEW_USDT",base="NEW",quote="USDT",trade_status="tradable",amount_precision=3,precision=2,min_base_amount=".001",min_quote_amount="5")]
    c.fetch=fetch
    try:
        markets=c.load_markets()
        assert "NEW/USDT" in markets and markets["NEW/USDT"]["active"] is True
        assert paths=={"okx":["/api/v5/public/instruments"],"binance":["/api/v3/exchangeInfo"],"gate":["/api/v4/margin/currency_pairs","/api/v4/spot/currency_pairs"]}[name]
    finally:c.close()


@pytest.mark.parametrize("info",[{"trade_status":"sellable","min_base_amount":".001"},{"trade_status":"tradable"}])
def test_gate_cannot_use_margin_active_or_inferred_minimum_as_spot_permission(info):
    c,t=fixture("gate",symbols=("BTC",));c.markets["BTC/USDT"]["info"]=info
    r=evaluate(c,c.markets,t,DiscoveryQuery(exchange="gate"),NOW)
    assert r["eligible"]==0 and "Gate" in r["rows"][0]["reasons"][0]


@pytest.mark.parametrize("name",["okx","binance","gate"])
def test_native_ticker_discovery_uses_one_batch_request_with_explicit_time_quality(name):
    c,_=fixture(name,symbols=("BTC",));paths=[]
    def fetch(url,method,headers,body):
        paths.append(urlparse(url).path);assert method=="GET"
        if name=="okx":return {"code":"0","data":[dict(instType="SPOT",instId="BTCUSDT",last="100",bidPx="100",askPx="100.1",open24h="99",high24h="105",low24h="95",vol24h="20000",volCcy24h="2000000",ts=str(NOW*1000))]}
        if name=="binance":return [dict(symbol="BTCUSDT",lastPrice="100",bidPrice="100",askPrice="100.1",openPrice="99",highPrice="105",lowPrice="95",quoteVolume="2000000",volume="20000",priceChangePercent="1",closeTime=NOW*1000)]
        return [dict(currency_pair="BTCUSDT",last="100",highest_bid="100",lowest_ask="100.1",high_24h="105",low_24h="95",quote_volume="2000000",base_volume="20000",change_percentage="1")]
    c.fetch=fetch
    ticks=getattr(ccxt,name).fetch_tickers(c,params={"type":"spot"})
    assert paths==[{"okx":"/api/v5/market/tickers","binance":"/api/v3/ticker/24hr","gate":"/api/v4/spot/tickers"}[name]]
    assert ticks["BTC/USDT"]["quoteVolume"]==2_000_000
    if name=="gate":
        c.markets["BTC/USDT"]["info"]={"trade_status":"tradable","min_base_amount":".001"}
        assert ticks["BTC/USDT"]["timestamp"] is None
    result=evaluate(c,c.markets,ticks,DiscoveryQuery(exchange=name),NOW)
    assert result["eligible"]==(0 if name=="gate" else 1)
    if name=="gate":assert "时间" in result["rows"][0]["reasons"][0]
