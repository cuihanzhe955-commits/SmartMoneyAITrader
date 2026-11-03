"""Exercise installed CCXT signing and order encoding with network transport intercepted."""

import json
from urllib.parse import urlparse, parse_qs
import ccxt
import pytest
from execution.venue import Venue


@pytest.mark.parametrize("name", ["okx", "binance"])
@pytest.mark.parametrize("swap", [False, True])
def test_signed_ioc_request(name, swap):
    cls = ccxt.okx if name == "okx" else ccxt.binanceusdm if swap else ccxt.binance
    ex = cls(
        {
            "apiKey": "unit-test-key",
            "secret": "unit-test-secret",
            "password": "unit-test-pass",
            "options": {"defaultType": "swap" if swap else "spot"},
        }
    )
    v = Venue.__new__(Venue)
    v.client = ex
    v.name = name
    v.swap = swap
    v.env = "live"
    symbol = v.pair("BTC")
    kind = "swap" if swap else "spot"
    market = dict(
        id=("BTC-USDT-SWAP" if swap else "BTC-USDT") if name == "okx" else "BTCUSDT",
        symbol=symbol,
        base="BTC",
        quote="USDT",
        baseId="BTC",
        quoteId="USDT",
        settle="USDT" if swap else None,
        settleId="USDT" if swap else None,
        type=kind,
        spot=not swap,
        margin=False,
        swap=swap,
        future=False,
        option=False,
        contract=swap,
        linear=swap,
        inverse=False,
        contractSize=1,
        active=True,
        precision={"amount": 0.001, "price": 0.01},
        limits={
            "amount": {"min": 0.001, "max": None},
            "cost": {"min": 1, "max": None},
            "price": {"min": 0.01, "max": None},
        },
        info={"orderTypes": ["LIMIT"], "filters": []},
    )
    ex.set_markets([market])
    ex.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
    captured = []

    def transport(url, method, headers, body):
        captured.append((url, method, headers, body))
        if name == "okx":
            return {
                "code": "0",
                "data": [{"ordId": "123", "clOrdId": "smtest", "sCode": "0"}],
            }
        return {
            "symbol": "BTCUSDT",
            "orderId": 123,
            "status": "NEW",
            "clientOrderId": "smtest",
            "price": "100",
            "origQty": "1",
            "executedQty": "0",
            "timeInForce": "IOC",
            "type": "LIMIT",
            "side": "SELL",
        }

    ex.fetch = transport
    result = v.submit(
        {"client_id": "smtest", "symbol": "BTC", "side": "SELL"},
        {"quantity": 1, "price": 100},
    )
    assert str(result["id"]) == "123" and len(captured) == 1
    url, method, headers, body = captured[0]
    assert method == "POST"
    if name == "okx":
        payload = json.loads(body)
        payload = payload[0] if isinstance(payload, list) else payload
        assert (
            payload["ordType"] == "ioc"
            and payload["clOrdId"] == "smtest"
            and headers["OK-ACCESS-SIGN"]
        )
        assert payload["tdMode"] == ("isolated" if swap else "cash")
        if swap:
            assert str(payload["reduceOnly"]).lower() == "true"
    else:
        args = parse_qs(body or urlparse(url).query)
        assert (
            args["timeInForce"] == ["IOC"]
            and args["newClientOrderId"] == ["smtest"]
            and args["signature"]
        )
        assert ("/fapi/v1/order" if swap else "/api/v3/order") in url
        if swap:
            assert args["reduceOnly"] == ["true"]
