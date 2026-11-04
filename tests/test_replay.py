import json
import pytest
from fastapi.testclient import TestClient
from terminal.api import create_app
from terminal.runtime import Runtime
from terminal.config import Session
from terminal.replay import replay
from market.feeds import START,historical
from challenge.manager import scan


@pytest.fixture
def archive(tmp_path):
    rt=Runtime(tmp_path)
    with rt.db.db:
        s=rt.new(Session(consent=True))
        for minute in range(181):scan(rt.db,s,START+minute*60,historical(START+minute*60))
        rt.db.save(s)
    try:yield rt,s
    finally:rt.shutdown();rt.db.db.close()


def test_candles_and_ledger_only_include_recorded_past(archive):
    rt,s=archive;fills=rt.db.entries("fills",s["id"])
    assert fills
    record=fills[-1];cutoff=record["t"]
    r=replay(rt.db,s["id"],record["symbol"],cutoff)
    assert max(v["time"] for v in r["candles"])<=cutoff
    assert all(v["t"]<=cutoff and v["challenge_id"]==s["id"] for v in r["fills"]+r["decisions"])
    assert record["id"] in {v["id"] for v in r["fills"]}
    assert r["read_only"] and not r["changes_sessions"]
    json.dumps(r,allow_nan=False)


@pytest.mark.parametrize("symbol,t",[("UNKNOWN",START),("BTC",START-60),("BTC",START+181*60),("BTC",START+1)])
def test_future_before_session_or_invalid_replay_is_rejected(archive,symbol,t):
    rt,s=archive
    with pytest.raises(ValueError):replay(rt.db,s["id"],symbol,t)


def test_other_session_records_cannot_leak_into_replay(archive):
    rt,s=archive
    with rt.db.db:
        rt.command(s["id"],"stop")
        other=rt.new(Session(consent=True));other["t"]=START
        rt.db.record("fills",other,"BUY",symbol="BTC",data={"private_fixture":"other session"})
    assert all(v["challenge_id"]==s["id"] for v in replay(rt.db,s["id"],"BTC",START)["fills"])


def test_realtime_session_has_no_fabricated_historical_candles(tmp_path):
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:s=rt.new(Session(consent=True,source="public"))
        with pytest.raises(ValueError,match="不回填"):replay(rt.db,s["id"],"BTC",s["t"])
    finally:rt.shutdown();rt.db.db.close()


def test_api_replay_does_not_change_session_or_create_orders(tmp_path):
    with TestClient(create_app(tmp_path)) as api:
        created=api.post("/api/sessions",json={"consent":True}).json()
        before=api.get("/api/state").json()
        r=api.get(f"/api/replay?session_id={created['id']}&symbol=BTC&as_of={START}")
        assert r.status_code==200 and len(r.json()["candles"])==240
        assert api.get(f"/api/replay?session_id={created['id']}&symbol=BTC&as_of={START+60}").status_code==400
        after=api.get("/api/state").json()
        assert after["state"]==before["state"] and after["fills"]==before["fills"]


@pytest.mark.parametrize("session_id",[0,-1,True])
def test_invalid_session_identity_never_defaults_to_latest_session(archive,session_id):
    rt,s=archive
    with pytest.raises(ValueError,match="会话编号"):replay(rt.db,session_id,"BTC",START)
