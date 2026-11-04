"""Installed CCXT spot contract POCs; synthetic protocol fixtures, HTTP intercepted."""
import time
from unittest.mock import Mock
from urllib.parse import urlparse
import ccxt
import pytest

NAMES=("okx","binance","gate")
T=1722816000000


def client(name):
    c=getattr(ccxt,name)({"apiKey":"fixture-key","secret":"fixture-secret","password":"fixture-pass",
        "enableRateLimit":False,"options":{"defaultType":"spot","fetchCurrencies":False}})
    c.set_markets([dict(id={"okx":"BTC-USDT","binance":"BTCUSDT","gate":"BTC_USDT"}[name],
        symbol="BTC/USDT",base="BTC",quote="USDT",baseId="BTC",quoteId="USDT",type="spot",spot=True,
        swap=False,future=False,option=False,contract=False,active=True,linear=False,inverse=False,
        precision={"amount":.001,"price":.01},limits={"amount":{"min":.001},"price":{},"cost":{"min":1}},
        info={"orderTypes":["LIMIT"],"filters":[]})])
    return c


@pytest.mark.parametrize("name",NAMES)
def test_native_ohlcv_response_has_common_base_volume_units(name):
    c=client(name);requests=[]
    def fetch(url,method,headers,body):
        requests.append(urlparse(url).path)
        assert method=="GET"
        if name=="okx":return {"code":"0","data":[[str(T),"100","102","99","101","2","2","202","1"]]}
        if name=="binance":return [[T,"100","102","99","101","2",T+59999,"202",10,"1","101","0"]]
        return [[str(T//1000),"202","101","102","99","100","2","true"]]
    c.fetch=fetch
    rows=c.fetch_ohlcv("BTC/USDT","1m",limit=1)
    assert rows==[[T,100.0,102.0,99.0,101.0,2.0]]
    assert len(requests)==1 and requests[0]=={"okx":"/api/v5/market/candles","binance":"/api/v3/klines","gate":"/api/v4/spot/candlesticks"}[name]


@pytest.mark.parametrize("name",NAMES)
def test_native_spot_balance_preserves_free_frozen_and_total(name):
    c=client(name);paths=[]
    def fetch(url,method,headers,body):
        path=urlparse(url).path;paths.append(path);assert method=="GET"
        if path.endswith("/account/detail"):
            return {"user_id":12345,"key":{"mode":1},"unified_account":"disabled"}
        if name=="okx":return {"code":"0","data":[{"uTime":str(T),"details":[{"ccy":"USDT","eq":"12","availBal":"10","frozenBal":"2"}]}]}
        if name=="binance":return {"updateTime":T,"balances":[{"asset":"USDT","free":"10","locked":"2"}]}
        return [{"currency":"USDT","available":"10","locked":"2"}]
    c.fetch=fetch
    b=c.fetch_balance({"type":"spot"})
    assert b["free"]["USDT"]==10 and b["used"]["USDT"]==2 and b["total"]["USDT"]==12
    assert paths[-1]=={"okx":"/api/v5/account/balance","binance":"/api/v3/account","gate":"/api/v4/spot/accounts"}[name]


@pytest.mark.parametrize("name",NAMES)
@pytest.mark.parametrize("error",[ccxt.RequestTimeout,ccxt.RateLimitExceeded])
def test_uncertain_or_rate_limited_post_is_not_blindly_repeated(name,error):
    c=client(name);posts=[]
    def fetch(url,method,headers,body):
        if urlparse(url).path.endswith("/account/detail"):
            return {"user_id":12345,"key":{"mode":1},"unified_account":"disabled"}
        assert method=="POST";posts.append((url,body));raise error("fixture failure after dispatch")
    c.fetch=fetch
    with pytest.raises(error):
        c.create_order("BTC/USDT","limit","buy",.01,100,{"timeInForce":"IOC","clientOrderId":"t-fixture" if name=="gate" else "fixture"})
    assert len(posts)==1


@pytest.mark.parametrize("name",NAMES)
def test_native_amount_precision_truncates_and_price_precision_rounds(name):
    c=client(name)
    assert c.amount_to_precision("BTC/USDT","0.01999")=="0.019"
    assert c.price_to_precision("BTC/USDT","100.006")=="100.01"
    with pytest.raises(ccxt.InvalidOrder):c.amount_to_precision("BTC/USDT","0.0001")
