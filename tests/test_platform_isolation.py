import copy,json,itertools
from unittest.mock import Mock,patch
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from terminal.config import Session
from terminal.runtime import Runtime
from terminal.api import create_app
from execution.platforms import registry
from execution.venue import Venue
from execution import live


@pytest.mark.parametrize("old,new",list(itertools.permutations(("okx","binance","gate"),2)))
def test_platform_switch_creates_independent_budget_orders_risk_and_archive(tmp_path,old,new):
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True,exchange=old,capital=10))
            rt.command(s["id"],"start")
            with pytest.raises(ValueError,match="结束"):rt.new(Session(consent=True,exchange=new))
            s=rt.db.load();s.update(cash=7,realized=-3,fees=.2,breaker=True,max_dd=30)
            rt.db.save(s);rt.command(s["id"],"stop");archived=rt.db.load()
            nxt=rt.new(Session(consent=True,exchange=new,capital=20))
            assert nxt["id"]!=s["id"] and nxt["account_ref"]!=archived["account_ref"]
            assert nxt["cash"]==20 and not nxt["positions"] and not nxt.get("paper_pending")
            assert not nxt["breaker"] and nxt["fees"]==nxt["realized"]==nxt["max_dd"]==0
            assert rt.db.load(s["id"])==archived
            assert not nxt.get("discovery_report") and not nxt.get("dynamic_rules")
    finally:rt.shutdown();rt.db.db.close()


@pytest.mark.parametrize("old_env",["demo","live"])
@pytest.mark.parametrize("reason",["positions","needs_check","recovery_required","pending"])
def test_remote_assets_in_any_environment_block_new_platform_even_paper(tmp_path,old_env,reason):
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True));s["config"]["execution"]=old_env;s["lifecycle_status"]="STOPPED"
            s[reason]={"BTC":dict(qty=.1)} if reason=="positions" else True
            rt.db.save(s)
            before=rt.db.load()
            with pytest.raises(ValueError,match="原账户交接"):rt.new(Session(consent=True,exchange="gate"))
            assert rt.db.load()==before
    finally:rt.shutdown();rt.db.db.close()


@pytest.mark.parametrize("env",["demo","live"])
def test_gate_private_execution_cannot_be_enabled_from_form_or_adapter(env):
    with pytest.raises(ValidationError,match="未验收"):
        Session(consent=True,exchange="gate",execution=env,source="public",confirmation="启用实盘")
    with patch("execution.venue.ccxt.gate") as factory:
        with pytest.raises(ValueError,match="未验收"):Venue("gate","spot",env,{"key":"fixture","secret":"fixture"})
        factory.assert_not_called()


def test_ended_paper_holdings_stay_in_their_original_archive(tmp_path):
    rt=Runtime(tmp_path)
    try:
        with rt.db.db:
            s=rt.new(Session(consent=True));s["positions"]={"BTC":dict(qty=.1,price=100,cost=10,opened=s["t"],entry=100,high=100)}
            s["cash"]-=10;rt.db.save(s);rt.command(s["id"],"stop")
            old=rt.db.load();new=rt.new(Session(consent=True,exchange="binance"))
            assert not new["positions"] and rt.db.load(old["id"])==old
    finally:rt.shutdown();rt.db.db.close()


def test_restart_does_not_move_active_platform_or_archive_ledger(tmp_path):
    rt=Runtime(tmp_path)
    with rt.db.db:
        s=rt.new(Session(consent=True,exchange="gate",capital=10));rt.command(s["id"],"start")
    before=rt.db.load();rt.shutdown();rt.db.db.close()
    recovered=Runtime(tmp_path)
    try:
        assert recovered.db.load()==before
        assert recovered.platform_status()["active"]["exchange"]=="gate"
        with recovered.db.db:
            with pytest.raises(ValueError,match="结束"):recovered.new(Session(consent=True,exchange="okx"))
    finally:recovered.shutdown();recovered.db.db.close()


def test_capabilities_do_not_claim_platform_or_real_funds_verification():
    items=registry();assert len(items)==3
    assert all(not x["platform_integration_verified"] and not x["real_funds_verified"] for x in items)
    assert next(x for x in items if x["exchange"]=="gate")["live"] is False


def test_platform_api_reflects_real_local_state_without_credentials(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        data=client.get("/api/platforms").json();assert data["active"] is None
        s=client.post("/api/sessions",json=dict(consent=True,exchange="gate",capital=10)).json()
        data=client.get("/api/platforms").json()
        assert data["active"]["session_id"]==s["id"] and data["switch_blockers"]
        assert data["active"]["execution"]=="paper"
        rejected=client.post("/api/sessions",json=dict(consent=True,exchange="binance"))
        assert rejected.status_code==400
        assert client.get("/api/state").json()["state"]["id"]==s["id"]
        assert not any(word in json.dumps(data) for word in ("apiKey","secret","passphrase"))


@pytest.mark.parametrize("name",["okx","binance","gate"])
def test_public_adapter_constructor_never_uses_credentials_and_loads_spot_rules(name):
    from test_discovery import fixture
    c,_=fixture(name,symbols=("BTC",))
    c.markets["BTC/USDT"]["info"]={"trade_status":"tradable","min_base_amount":".001"}
    with patch("execution.venue.ccxt."+name,return_value=c) as factory:
        v=Venue(name,"spot","public")
        params=factory.call_args.args[0]
        assert "apiKey" not in params and "secret" not in params
        assert c.load_markets.call_count==1 and not c.session.trust_env
        assert v.public_rules(["BTC"])["BTC"]["exchange"]==name
    c.close()


@pytest.mark.parametrize("info",[{"trade_status":"sellable","min_base_amount":".001"},{"trade_status":"tradable"}])
def test_gate_public_rules_do_not_infer_spot_execution_from_margin_metadata(info):
    from test_discovery import fixture
    c,_=fixture("gate",symbols=("BTC",));c.markets["BTC/USDT"]["info"]=info
    v=Venue.__new__(Venue);v.client=c;v.name="gate";v.env="public";v.swap=False
    assert v.public_rules(["BTC"])=={}
    c.close()
