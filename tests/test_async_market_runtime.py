import threading,time
from unittest.mock import Mock,patch
import pytest
from terminal.runtime import Runtime
from terminal.config import Session
from market.feeds import START,historical
from execution.venue import Venue


def setup(tmp_path):
    rt=Runtime(tmp_path);rt.background=True
    with rt.db.db:
        s=rt.new(Session(consent=True,source="public",strict_min=999999));rt.command(s["id"],"start")
    return rt


def bars():
    offset=int(time.time())-START
    return {k:[(r[0]+offset,*r[1:]) for r in rows] for k,rows in historical(START).items()}


def test_background_paper_fetch_is_nonblocking_and_applies_verified_result(tmp_path):
    rt=setup(tmp_path);entered,release=threading.Event(),threading.Event();v=Mock()
    def slow(*args,**kwargs):entered.set();assert release.wait(3);return bars()
    v.bars.side_effect=slow
    try:
        with patch("terminal.runtime.Venue",return_value=v) as factory:
            start=time.monotonic();rt.tick();assert time.monotonic()-start<.3
            assert entered.wait(2)
            for _ in range(5):rt.tick()
            assert factory.call_count==1 and rt.db.load()["last_scan"]==0
            assert rt.db.load()["market_fetch"]["status"]=="WAITING"
            release.set();assert rt.market_worker.flight.done.wait(2);rt.tick()
            state=rt.db.load();assert state["feed_valid"] and state["last_scan"]
            assert state["market_fetch"]["status"]=="READY"
            assert factory.call_args.args==("okx","spot","public")
            v.client.session.close.assert_not_called()
            rt.public_market_client.close()
            v.client.session.close.assert_called_once()
    finally:release.set();rt.shutdown();rt.db.db.close()


def test_pause_discards_result_without_resuming_or_writing_closed_ledger(tmp_path):
    rt=setup(tmp_path);entered,release=threading.Event(),threading.Event();v=Mock()
    def slow(*args,**kwargs):entered.set();assert release.wait(3);return bars()
    v.bars.side_effect=slow
    try:
        with patch("terminal.runtime.Venue",return_value=v):
            rt.tick();assert entered.wait(2)
            with rt.db.db:rt.command(rt.db.load()["id"],"pause")
            release.set();assert rt.market_worker.flight.done.wait(2);rt.tick()
            assert rt.db.load()["lifecycle_status"]=="PAUSED" and rt.db.load()["last_scan"]==0
    finally:release.set();rt.shutdown();rt.db.db.close()


def test_timeout_rejects_late_market_data(tmp_path):
    rt=setup(tmp_path);entered,release=threading.Event(),threading.Event();clock=[time.monotonic()];rt.market_worker.clock=lambda:clock[0];v=Mock()
    def slow(*args,**kwargs):entered.set();assert release.wait(3);return bars()
    v.bars.side_effect=slow
    try:
        with patch("terminal.runtime.Venue",return_value=v):
            rt.tick();assert entered.wait(2);clock[0]+=31;rt.tick()
            state=rt.db.load();assert state["lifecycle_status"]=="DATA_STALE" and not state["feed_valid"]
            assert not rt.db.entries("fills",state["id"])
            release.set();assert rt.market_worker.flight.done.wait(2)
            assert rt.market_worker.poll(rt.market_worker.flight.scope) is None
    finally:release.set();rt.shutdown();rt.db.db.close()


def test_shutdown_does_not_wait_for_public_fetch_or_let_it_touch_ledger(tmp_path):
    rt=setup(tmp_path);entered,release=threading.Event(),threading.Event();v=Mock()
    def slow(*args,**kwargs):entered.set();assert release.wait(3);return bars()
    v.bars.side_effect=slow
    with patch("terminal.runtime.Venue",return_value=v):
        rt.tick();assert entered.wait(2);task=rt.market_worker.flight
        start=time.monotonic();rt.shutdown();assert time.monotonic()-start<.3
        rt.db.db.close();release.set();assert task.done.wait(2)
        assert task.cancel.is_set() and task.value is None
        v.client.session.close.assert_called_once()


@pytest.mark.parametrize("cancelled",[True,False])
def test_cancel_or_expired_deadline_stops_before_next_symbol_request(cancelled):
    v=Venue.__new__(Venue);v.name="okx";v.swap=False;v.client=Mock();v.client.markets={"BTC/USDT":{}}
    event=threading.Event()
    if cancelled:event.set()
    with pytest.raises(ValueError,match="取消或超时"):v.bars(["BTC"],cancel=event,deadline=None if cancelled else 0)
    v.client.fetch_ohlcv.assert_not_called()


def test_regional_refusal_still_pauses_instead_of_retrying_as_ordinary_network_error(tmp_path):
    rt=setup(tmp_path);v=Mock();v.bars.side_effect=RuntimeError("HTTP 451 restricted location fixture")
    try:
        with patch("terminal.runtime.Venue",return_value=v) as factory:
            rt.tick();assert rt.market_worker.flight.done.wait(2);rt.tick()
            assert rt.db.load()["lifecycle_status"]=="PAUSED"
            assert "451" in rt.db.load()["latest"]
            rt.tick();assert factory.call_count==1
    finally:rt.shutdown();rt.db.db.close()


def test_runtime_reuses_public_client_across_two_completed_scan_cycles(tmp_path):
    rt=setup(tmp_path);v=Mock();v.bars.side_effect=lambda *a,**k:bars()
    try:
        with patch("terminal.runtime.Venue",return_value=v) as factory:
            for _ in range(2):
                with rt.db.db:
                    state=rt.db.load();state["next_scan"]=int(time.time())-1;rt.db.save(state)
                rt.tick();assert rt.market_worker.flight.done.wait(2);rt.tick()
                assert rt.db.load()["feed_valid"]
            assert factory.call_count==1 and v.bars.call_count==2
            v.client.session.close.assert_not_called()
            rt.shutdown();v.client.session.close.assert_called_once()
    finally:rt.shutdown();rt.db.db.close()
