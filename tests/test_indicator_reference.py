import copy
import json
import math
from pathlib import Path

import pytest

from strategy.indicators import ema,rsi,atr
from strategy.research import compare
from market.feeds import START, SYMBOLS

REFERENCE=json.loads((Path(__file__).resolve().parents[1]/"data/indicator-reference.json").read_text())


@pytest.mark.parametrize("name",list(REFERENCE["cases"]))
def test_full_series_matches_independent_talib_vectors(name):
    case=REFERENCE["cases"][name];rows=case["rows"];closes=[r[4] for r in rows]
    actual=dict(ema9=ema(closes,9),ema21=ema(closes,21),rsi=rsi(closes),atr=atr([r[2] for r in rows],[r[3] for r in rows],closes))
    for key,seq in actual.items():
        expected=case["expected"][key]
        assert len(seq)==len(expected)
        for a,b in zip(seq,expected):
            if b is None:assert a is None
            else:assert a==pytest.approx(b,rel=1e-11,abs=1e-10)


@pytest.mark.parametrize("cut",[5,14,21,60,130,200])
def test_prefix_results_do_not_change_when_future_bars_are_appended(cut):
    rows=REFERENCE["cases"]["random"]["rows"];closes=[r[4] for r in rows]
    assert ema(closes[:cut],9)==ema(closes,9)[:cut]
    assert rsi(closes[:cut])==rsi(closes)[:cut]
    assert atr([r[2] for r in rows[:cut]],[r[3] for r in rows[:cut]],closes[:cut])==atr([r[2] for r in rows],[r[3] for r in rows],closes)[:cut]


@pytest.mark.parametrize("bad",[None,float("nan"),float("inf"),True,"100"])
def test_missing_and_non_finite_data_are_rejected_not_imputed(bad):
    for compute in (lambda:ema([100,bad],9),lambda:rsi([100,bad]),lambda:atr([101,101],[99,99],[100,bad])):
        with pytest.raises(ValueError):compute()


@pytest.mark.parametrize("period",[0,1,True,2.5,100001])
def test_invalid_indicator_period_is_rejected(period):
    with pytest.raises(ValueError):ema([1,2,3],period)
    with pytest.raises(ValueError):rsi([1,2,3],period)


def test_atr_shape_and_price_validation():
    with pytest.raises(ValueError):atr([101],[99,99],[100])
    with pytest.raises(ValueError):atr([99],[101],[100])
    assert ema([],9)==[] and rsi([])==[] and atr([],[],[])==[]


@pytest.mark.parametrize("symbol",SYMBOLS)
def test_research_uses_real_archive_and_keeps_legacy_engine(symbol):
    result=compare(symbol)
    assert result["as_of"]==START and result["bars"]==240
    assert result["production_method"]=="legacy" and not result["engine_changed"]
    assert max(r["time"] for r in result["bars_preview"])<=START
    assert len(result["comparisons"])==4
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize("symbol,offset",[("UNKNOWN",0),("BTC",-1),("BTC",1441),("BTC",True),("BTC",1.5)])
def test_research_rejects_outside_archive_or_invalid_parameters(symbol,offset):
    with pytest.raises(ValueError):compare(symbol,offset)


def test_research_api_does_not_create_or_modify_trading_session(tmp_path):
    from fastapi.testclient import TestClient
    from terminal.api import create_app
    with TestClient(create_app(tmp_path)) as client:
        assert client.post("/api/sessions",json={"consent":True}).status_code==200
        before=client.get("/api/state").json()
        response=client.get("/api/research/indicators?symbol=ETH&offset_minute=360")
        assert response.status_code==200
        report=response.json()
        assert report["symbol"]=="ETH" and report["as_of"]==START+360*60
        assert report["read_only"] and not report["changes_sessions"]
        for query,status in (("symbol=UNKNOWN",400),("offset_minute=-1",400),("offset_minute=1.5",422)):
            assert client.get("/api/research/indicators?"+query).status_code==status
        after=client.get("/api/state").json()
        for key in ("state","fills","curve"):
            assert after[key]==before[key]
