"""Exercise production spot preparation with native CCXT precision; no network."""
import math
import time
from decimal import Decimal
from unittest.mock import Mock
import ccxt
import pytest
from execution.venue import Venue


def venue(name="okx"):
    v=Venue.__new__(Venue);v.name=name;v.env="demo";v.swap=False
    v.client=getattr(ccxt,name)({"enableRateLimit":False})
    v.client.set_markets([dict(id="BTC-USDT" if name=="okx" else "BTCUSDT",symbol="BTC/USDT",
        base="BTC",quote="USDT",baseId="BTC",quoteId="USDT",type="spot",spot=True,
        swap=False,future=False,option=False,contract=False,active=True,linear=False,inverse=False,
        precision={"amount":.000001,"price":1},limits={"amount":{"min":.000001},"price":{},"cost":{}})])
    v.client.load_markets=Mock(return_value=v.client.markets)
    v.client.fetch_open_orders=Mock(return_value=[])
    v.client.fetch_balance=Mock(return_value={"free":{"USDT":100,"BTC":1}})
    v.client.fetch=Mock(side_effect=AssertionError("external transport forbidden"))
    v.quote=Mock(return_value=(100.3,100.49,time.time()))
    return v


@pytest.mark.parametrize("name",["okx","binance"])
def test_price_rounding_up_never_spends_above_target_budget(name):
    v=venue(name)
    p=v.prepare("BTC","BUY",20,0,100.49,1)
    assert p["price"]==101
    assert Decimal(str(p["quantity"]))*Decimal(str(p["price"]))<=Decimal("20")
    v.client.fetch.assert_not_called()


@pytest.mark.parametrize("value",[float("nan"),float("inf"),-1,True,"100"])
def test_unusable_available_balance_fails_before_order_preparation(value):
    v=venue();v.client.fetch_balance.return_value={"free":{"USDT":value,"BTC":1}}
    with pytest.raises(ValueError,match="余额"):
        v.prepare("BTC","BUY",20,0,100.49,1)


@pytest.mark.parametrize("side,field,value",[("BUY","amount",float("nan")),("BUY","amount",0),("SELL","holding",-1),("BUY","reference",0),("BUY","reference",True),("UNKNOWN","amount",20)])
def test_invalid_request_is_rejected_before_market_requests(side,field,value):
    v=venue();args=dict(k="BTC",side=side,amount=20,holding=.2,reference=100.49,leverage=1);args[field]=value
    with pytest.raises(ValueError):v.prepare(**args)
    v.client.load_markets.assert_not_called()


def test_price_rounding_cannot_bypass_reference_deviation_limit():
    v=venue();v.client.market("BTC/USDT")["precision"]["price"]=3
    with pytest.raises(ValueError,match="参考价"):
        v.prepare("BTC","BUY",20,0,100.49,1)


def test_precision_adapter_must_not_round_quantity_up():
    v=venue();v.client.amount_to_precision=Mock(return_value=".2")
    with pytest.raises(ValueError,match="预算|精度"):
        v.prepare("BTC","BUY",20,0,100.49,1)


def test_sell_precision_never_exceeds_owned_quantity():
    v=venue();v.client.amount_to_precision=Mock(return_value=".200001")
    with pytest.raises(ValueError,match="持仓|精度"):
        v.prepare("BTC","SELL",0,.2,100.49,1)
