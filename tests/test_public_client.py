import threading
import time
from unittest.mock import Mock, patch
import pytest
from market.public_client import PublicClientCache
from execution.venue import Venue


def request(cache, factory, exchange="okx", product="spot", event=None):
    return cache.fetch(factory, exchange, product, ("BTC",), (),
                       event or threading.Event(), time.monotonic()+20)


def test_reuses_client_and_refreshes_metadata_after_ttl():
    clock=[0];cache=PublicClientCache(clock=lambda:clock[0]);factory=Mock()
    first,second=Mock(),Mock();factory.side_effect=[first,second]
    request(cache,factory);clock[0]=599;request(cache,factory)
    assert factory.call_count==1 and first.bars.call_count==2
    clock[0]=600;request(cache,factory)
    assert factory.call_count==2
    first.client.session.close.assert_called_once()
    cache.close();second.client.session.close.assert_called_once()


@pytest.mark.parametrize("exchange,product",[("binance","spot"),("okx","swap")])
def test_platform_or_product_switch_disposes_previous_public_transport(exchange,product):
    cache=PublicClientCache();first,second=Mock(),Mock();factory=Mock(side_effect=[first,second])
    request(cache,factory);request(cache,factory,exchange,product)
    assert factory.call_args.args==(exchange,product,"public")
    first.client.session.close.assert_called_once()
    cache.close()


def test_failed_request_discards_connection_and_next_request_recreates():
    cache=PublicClientCache();first,second=Mock(),Mock();first.bars.side_effect=ValueError("fixture")
    factory=Mock(side_effect=[first,second])
    with pytest.raises(ValueError):request(cache,factory)
    first.client.session.close.assert_called_once()
    request(cache,factory);assert factory.call_count==2;cache.close()


def test_cancelled_request_does_not_construct_or_reuse_transport():
    cache=PublicClientCache();factory=Mock();cancel=threading.Event();cancel.set()
    with pytest.raises(ValueError,match="取消或超时"):request(cache,factory,event=cancel)
    factory.assert_not_called();cache.close()


def test_close_while_fetching_is_nonblocking_rejects_reuse_and_closes_after_return():
    cache=PublicClientCache();entered,release=threading.Event(),threading.Event();v=Mock()
    v.bars.side_effect=lambda *a,**k:(entered.set(),release.wait(2),{})[-1]
    thread=threading.Thread(target=lambda:request(cache,Mock(return_value=v)))
    thread.start()
    try:
        assert entered.wait(1)
        with pytest.raises(ValueError,match="正在使用"):request(cache,Mock())
        start=time.monotonic();cache.close();assert time.monotonic()-start<.2
        v.client.session.close.assert_not_called()
        with pytest.raises(ValueError,match="关闭"):request(cache,Mock())
    finally:release.set();thread.join(2)
    assert not thread.is_alive();v.client.session.close.assert_called_once()
    cache.close();v.client.session.close.assert_called_once()


def test_cancel_during_metadata_loading_never_requests_candles():
    cache=PublicClientCache();v=Mock();cancel=threading.Event()
    def construct(*args):cancel.set();return v
    with pytest.raises(ValueError,match="取消或超时"):request(cache,construct,event=cancel)
    v.bars.assert_not_called();v.client.session.close.assert_called_once();cache.close()


@pytest.mark.parametrize("fail",[False,True])
def test_per_request_timeout_is_clamped_to_remaining_budget_and_restored(fail):
    v=Venue.__new__(Venue);v.name="okx";v.swap=False;v.client=Mock()
    v.client.markets={"BTC/USDT":{}};v.client.timeout=8000
    def fetch(*args,**kwargs):
        assert 1 <= v.client.timeout <= 1500
        if fail:raise RuntimeError("fixture")
        return [[(time.time()-120)*1000,1,2,1,2,3]]
    v.client.fetch_ohlcv.side_effect=fetch
    result=v.bars(["BTC"],deadline=time.monotonic()+1.5)
    assert v.client.timeout==8000
    assert ("BTC" in result.errors) if fail else ("BTC" in result)


def test_cancel_after_http_response_drops_data_and_skips_remaining_symbols():
    v=Venue.__new__(Venue);v.name="okx";v.swap=False;v.client=Mock();v.client.timeout=8000
    v.client.markets={"BTC/USDT":{},"ETH/USDT":{}};cancel=threading.Event()
    def fetch(*args,**kwargs):cancel.set();return [[0,1,2,1,2,3]]
    v.client.fetch_ohlcv.side_effect=fetch
    with pytest.raises(ValueError,match="取消或超时"):
        v.bars(["BTC","ETH"],cancel=cancel,deadline=time.monotonic()+10)
    assert v.client.fetch_ohlcv.call_count==1 and v.client.timeout==8000


def test_failed_metadata_load_closes_transport():
    client=Mock();client.load_markets.side_effect=RuntimeError("fixture")
    with patch("execution.venue.ccxt.okx",return_value=client):
        with pytest.raises(RuntimeError):Venue("okx","spot","public")
    client.session.close.assert_called_once()


def test_deadline_reached_during_response_drops_result_and_restores_timeout():
    v=Venue.__new__(Venue);v.name="okx";v.swap=False;v.client=Mock();v.client.timeout=8000
    v.client.markets={"BTC/USDT":{}}
    v.client.fetch_ohlcv.return_value=[[0,1,2,1,2,3]]
    with patch("execution.venue.time.monotonic",side_effect=[0,0,2,2]):
        with pytest.raises(ValueError,match="取消或超时"):v.bars(["BTC"],deadline=1)
    assert v.client.timeout==8000 and v.client.fetch_ohlcv.call_count==1
