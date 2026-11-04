import json
import time
import threading
from unittest.mock import Mock, patch

import pytest
from ai.provider import Advice
from challenge.manager import scan
from execution import live
from execution.venue import Venue
from market.feeds import START, historical
from strategy.rules import analyze
from strategy.ensemble import enrich
from terminal.config import Session
from terminal.runtime import Runtime


def model(rt, fallback="rules"):
    rt.vault.update_many({"ai_key": "fixture", "ai_config": {"model": "mock", "fallback": fallback}})
    return Advice(symbol="BTC", action="BUY", fraction=.06, reason="test", risk="test", exit_plan="test")


def ai_session(rt, **changes):
    with rt.db.db:
        state = rt.new(Session(consent=True, engine="ai", speed=1, **changes))
        rt.command(state["id"], "start")
    return state


def test_slow_ai_scan_stop_and_stale_reply(tmp_path):
    rt = Runtime(tmp_path)
    entered, release = threading.Event(), threading.Event()
    proposal = model(rt)
    s = ai_session(rt, decision_interval=3600, strict_min=9999)
    def infer(*args):
        entered.set()
        release.wait(4)
        return "brief", proposal
    try:
        with patch("terminal.runtime.Provider.propose", side_effect=infer), patch("terminal.runtime.market_time", return_value=START) as clock:
            rt.tick()
            assert entered.wait(1)
            flight = rt.ai.worker.flight
            s = rt.db.load()
            price = historical(START)["BTC"][-1][4] * 1.1
            with rt.db.db:
                s["positions"]["BTC"] = dict(qty=.001, price=price, entry=price, high=price, cost=price*.001, opened=START)
                rt.db.save(s)
            clock.return_value = START + 60
            rt.tick()
            assert not flight.done.is_set()
            s = rt.db.load()
            assert s["last_scan"] == START+60 and s["paper_pending"]["BTC"]["side"] == "SELL"
            release.set()
            assert flight.done.wait(1)
            rt.tick()
            assert rt.db.entries("system_events", s["id"], kind="AI_SKIP")
            assert not rt.db.entries("system_events", s["id"], kind="AI")
    finally:
        release.set()
        rt.shutdown()
        rt.db.db.close()


@pytest.mark.parametrize("fallback", ["rules","hold","manual"])
def test_timeout_is_bounded_and_late_reply_discarded(tmp_path, fallback):
    rt = Runtime(tmp_path)
    gate = threading.Event()
    proposal = model(rt, fallback)
    s = ai_session(rt)
    try:
        with patch("terminal.runtime.Provider.propose", side_effect=lambda *a: (gate.wait(4) and "late", proposal)) as call:
            rt.tick()
            flight = rt.ai.worker.flight
            flight.deadline = time.monotonic()-1
            rt.tick()
            assert rt.db.load()["ai_failed"] and call.call_count == 1
            assert bool(rt.db.load().get("ai_manual")) == (fallback=="manual")
            if fallback != "rules":
                assert not any(o["side"]=="BUY" for o in rt.db.load().get("paper_pending",{}).values())
            gate.set()
            assert flight.done.wait(1)
            rt.tick()
            assert not rt.db.entries("system_events", s["id"], kind="AI")
            if fallback == "manual":
                with rt.db.db:
                    assert rt.command(s["id"],"use_rules")["engine_override"]=="rules"
    finally:
        gate.set()
        rt.shutdown()
        rt.db.db.close()


def exchange_session(rt):
    rt.vault.update("okx/live", {"key": "mock"})
    with rt.db.db:
        s = rt.new(Session(consent=True, execution="live", source="public", confirmation="启用实盘",capital=100))
        rt.command(s["id"], "start", "启用实盘")
        s=rt.db.load()
        s.update(lifecycle_status="RUNNING",admitted=True,local_armed=True,needs_check=False,recovery_required=False)
        rt.db.save(s)
    return s


@pytest.mark.parametrize("failure,expected", [
    ("timeout", "交易规则刷新失败，已阻止下单"),
    ("rate_limit", "交易所请求频率受限"),
    ("region", "HTTP 451"),
])
def test_rule_refresh_failure_reaches_status_and_order_record(tmp_path, failure, expected):
    import ccxt
    from test_acceptance import wire_venue
    rt = Runtime(tmp_path)
    try:
        s = exchange_session(rt)
        venue = wire_venue()
        secret = "fixture-private-response-must-not-be-displayed"
        error = (ccxt.RateLimitExceeded(secret) if failure == "rate_limit" else
                 ccxt.ExchangeNotAvailable("451 " + secret) if failure == "region" else
                 ccxt.RequestTimeout(secret))
        venue.client.load_markets = Mock(side_effect=error)
        venue.client.create_order = Mock()
        venue.audit = Mock(return_value={"dedicated_balance_match": True})
        rt.venue = lambda c: venue
        with rt.db.db:
            live.enqueue(rt.db, s, "BTC", "BUY", {"price": 100, "time": int(time.time())}, 10, "fixture")
            order = live.pending(rt.db, s["id"])
        rt.dispatch(s, order)
        current = rt.db.load()
        stored = json.loads(rt.db.db.execute("SELECT body FROM venue_orders WHERE client_id=?",
                            (order["client_id"],)).fetchone()[0])
        assert current["lifecycle_status"] == "PAUSED" and current["needs_check"]
        assert expected in current["latest"] and secret not in current["latest"]
        assert stored["stage"] == "REJECTED" and stored["error"] == current["latest"]
        assert stored["calculation"]["final_amount"] == 0
        assert not live.pending(rt.db, s["id"])
        events = rt.db.entries("system_events", s["id"], kind="REJECTED")
        assert len(events) == 1 and events[0]["summary"] == current["latest"]
        assert secret not in json.dumps(events)
        rt.dispatch(current, order)
        assert len(rt.db.entries("system_events", s["id"], kind="REJECTED")) == 1
        venue.client.create_order.assert_not_called()
    finally:
        rt.shutdown()
        rt.db.db.close()


def test_partial_cancel_race_and_actual_restart(tmp_path):
    rt=Runtime(tmp_path)
    s=exchange_session(rt)
    with rt.db.db:
        live.enqueue(rt.db,s,"BTC","BUY",{"price":10,"time":int(time.time())},20,"rule")
        o=live.pending(rt.db,s["id"])
        o["prepared"]=dict(quantity=2,price=10,contract=1)
        live.save(rt.db,o,"SENDING")
    venue=Mock()
    venue.lookup.return_value=dict(id="ex1",status="open",filled=.5)
    t1=dict(order="ex1",id="first",side="buy",price=10,amount=.5,fee=dict(currency="BTC",cost=.001))
    venue.executions.return_value=[t1]
    rt.venue=lambda c:venue
    rt.dispatch(s,o)
    state=rt.db.load()
    assert state["cash"]==95 and state["positions"]["BTC"]["qty"]==pytest.approx(.499)
    assert live.pending(rt.db,s["id"])["stage"]=="PARTIALLY_FILLED"
    rt.db.db.close()
    rt=Runtime(tmp_path)
    rt.venue=lambda c:venue
    rt.start_worker()
    try:
        deadline=time.monotonic()+3
        while venue.lookup.call_count<2 and time.monotonic()<deadline:
            time.sleep(.01)
    finally:
        rt.shutdown()
    assert venue.lookup.call_count>=2
    assert rt.db.load()["lifecycle_status"]=="PAUSED"
    assert rt.db.load()["cash"]==95
    with rt.db.db:
        rt.command(s["id"],"stop")
    venue.cancel.side_effect=TimeoutError()
    rt.dispatch(rt.db.load(),live.pending(rt.db,s["id"]))
    assert live.pending(rt.db,s["id"])["stage"]=="UNKNOWN"
    t2=dict(order="ex1",id="second",side="buy",price=12,amount=.5,fee=dict(currency="USDT",cost=.01))
    venue.lookup.return_value=dict(id="ex1",status="canceled",filled=1)
    venue.executions.return_value=[t1,t2,t2]
    rt.dispatch(rt.db.load(),live.pending(rt.db,s["id"]))
    final=rt.db.load()
    assert final["lifecycle_status"]=="STOPPED" and final["cash"]==pytest.approx(88.99)
    assert final["positions"]["BTC"]["qty"]==pytest.approx(.999)
    assert final["fees"]==pytest.approx(.02)
    assert not live.pending(rt.db,s["id"])
    assert rt.db.db.execute("select count(*) from venue_executions").fetchone()[0]==2
    receipt=rt.db.entries("fills",s["id"])[0]["data"]
    assert receipt["price"]==11 and set(receipt["trade_ids"])=={"first","second"}
    venue.submit.assert_not_called()
    venue.cancel.assert_called_once()
    rt.db.db.close()


def test_replayed_signal_and_orphan_guard(tmp_path):
    rt=Runtime(tmp_path); s=exchange_session(rt)
    with rt.db.db:
        m={"price":10,"time":int(time.time())}
        live.enqueue(rt.db,s,"BTC","BUY",m,10,"signal")
        o=live.pending(rt.db,s["id"])
        s["lifecycle_status"]="STOPPED"
        rt.db.save(s)
        with pytest.raises(ValueError, match="未完订单"):
            rt.new(Session(consent=True))
        live.save(rt.db,o,"CANCELLED")
        live.enqueue(rt.db,s,"BTC","BUY",m,5,"retry-other-model")
        assert rt.db.db.execute("select count(*) from venue_orders").fetchone()[0]==1
    rt.db.db.close()


@pytest.mark.parametrize("failure", ["withdraw","foreign_order","different_balance","other_asset","algo"])
def test_real_adapter_preflight_fails_closed(failure):
    v=Venue.__new__(Venue); v.name="okx";v.swap=False;v.env="live";v.client=Mock()
    v.client.privateGetAccountConfig.return_value={"code":"0","data":[{"uid":"dummy","perm":"read_only,trade"+(",withdraw" if failure=="withdraw" else "")}]}
    v.client.privateGetTradeOrdersAlgoPending.return_value={"code":"0","data":[{}] if failure=="algo" else []}
    v.client.markets={"BTC/USDT": {}}
    import ccxt
    v.client.precisionMode=ccxt.TICK_SIZE
    v.client.market.return_value={"active":True,"spot":True,
        "precision":{"amount":.000001,"price":.01}, "limits":{"amount":{"min":.000001},"cost":{}}}
    balances={"USDT":101 if failure=="different_balance" else 100}
    if failure=="other_asset":balances["BTC"]=1
    v.client.fetch_balance.return_value={"free":balances,"used":{},"total":balances}
    v.client.fetch_open_orders.return_value=[{}] if failure=="foreign_order" else []
    with pytest.raises(ValueError):
        v.preflight({"cash":100,"positions":{}})
    v.client.create_order.assert_not_called()


@pytest.mark.parametrize("engine", ["rules","ai"])
def test_two_engines_to_spot_intent_then_mock_venue(tmp_path, engine):
    rt=Runtime(tmp_path)
    prop=model(rt)
    rt.vault.update("okx/live",{"key":"fixture"})
    with rt.db.db:
        s=rt.new(Session(consent=True,engine=engine,execution="live",source="public",confirmation="启用实盘"))
        rt.command(s["id"],"start","启用实盘")
    c=s["config"]
    for i in range(180):
        t=START+i*60
        row=historical(t)["BTC"]
        metric=enrich(row,analyze(row,t,c),c)
        if metric["valid"] and metric["buy"]==(engine=="rules"):
            break
    else:
        pytest.fail("历史行情未覆盖所需信号")
    now=int(time.time())//60*60
    rt.feed=lambda *_:{"BTC":[(b[0]+now-t,*b[1:]) for b in row]}
    v=Mock();rt.venue=lambda c:v
    v.preflight.return_value={"venue_account_id":"mock","dedicated_balance_match":True,"checked":time.time()}
    v.audit.return_value={"dedicated_balance_match":True}
    v.prepare.side_effect=lambda sym,side,amount,held,ref,lev:dict(quantity=amount/ref,price=ref,contract=1,quote_time=time.time())
    v.submit.return_value={"id":"mock-receipt"}
    with patch("terminal.runtime.Provider.propose",return_value=("brief",prop)) as ai:
        rt.tick()
        if engine=="ai":
            assert rt.ai.worker.flight.done.wait(1)
            rt.tick()
        else:
            ai.assert_not_called()
        o=live.pending(rt.db,s["id"])
        assert o and o["source"]==engine and o["calculation"]["final_amount"]>0
        rt.tick()
        o=live.pending(rt.db,s["id"])
        assert o["stage"]=="SUBMITTED" and not rt.db.entries("fills",s["id"])
        prep=o["prepared"]
        v.lookup.return_value=dict(id="mock-receipt",status="closed",filled=prep["quantity"])
        v.executions.return_value=[dict(order="mock-receipt",id="one",side="buy",amount=prep["quantity"],
                                        price=prep["price"],fee=dict(cost=.01,currency="USDT"))]
        rt.tick()
        assert rt.db.load()["positions"]["BTC"]["qty"]==pytest.approx(prep["quantity"])
        assert rt.db.entries("fills",s["id"])[0]["data"]["decision_id"]==o["decision_id"]
        v.submit.assert_called_once()
    rt.shutdown();rt.db.db.close()


def test_book_stop_and_order_reconciliation_while_scanner_is_blocked(tmp_path):
    rt = Runtime(tmp_path)
    entered, release, sent = threading.Event(), threading.Event(), threading.Event()
    def blocked_scan(*args):
        entered.set()
        release.wait(10)
        return {}
    rt.feed = blocked_scan
    venue = Mock()
    rt.venue = lambda c: venue
    venue.preflight.return_value = {"venue_account_id": "test", "dedicated_balance_match": True, "checked": time.time()}
    venue.audit.return_value = {"dedicated_balance_match": True}
    venue.quote.side_effect = lambda k: (90, 90.01, time.time())
    venue.prepare.side_effect = lambda *a: dict(quantity=.5, price=90, contract=1, quote_time=time.time())
    def accept(order, prepared):
        assert order["source"] == "local_stop" and order["side"] == "SELL"
        sent.set()
        return {"id": "closed-stop"}
    venue.submit.side_effect = accept
    venue.lookup.return_value = {"id": "closed-stop", "filled": .5, "status": "closed"}
    venue.executions.return_value = [dict(id="stop-fill", side="sell", order="closed-stop", amount=.5,
                                          price=90, fee={"currency": "USDT", "cost": .01})]
    rt.start_worker()
    try:
        with rt.lock, rt.db.db:
            s = exchange_session(rt)
            s["positions"]["BTC"] = {"qty": .5, "cost": 50, "price": 100, "entry":100,
                                    "high":100, "opened":s["t"]}
            s["cash"] = 50
            rt.db.save(s)
        assert entered.wait(3)
        assert sent.wait(5) and not release.is_set()
        end=time.monotonic()+3
        while time.monotonic()<end:
            with rt.lock:
                if not rt.db.load()["positions"]:
                    break
            time.sleep(.02)
        with rt.lock:
            assert not rt.db.load()["positions"] and rt.db.load()["cash"] == pytest.approx(94.99)
        venue.submit.assert_called_once()
    finally:
        release.set()
        rt.shutdown()
        rt.db.db.close()


def test_invalid_receipt_rolls_back_entire_batch(tmp_path):
    rt=Runtime(tmp_path); s=exchange_session(rt)
    with rt.db.db:
        live.enqueue(rt.db,s,"BTC","BUY",{"price":10,"time":int(time.time())},20,"fixture")
        o=live.pending(rt.db,s["id"])
        o["prepared"]={"quantity":2,"price":10,"contract":1}
        live.save(rt.db,o,"SENDING")
    v=Mock();rt.venue=lambda c:v
    v.lookup.return_value={"id":"ex","status":"open","filled":2}
    v.executions.return_value=[dict(order="ex",id=i,side="buy",amount=1,price=p,
             fee={"currency":"USDT","cost":0}) for i,p in enumerate([10,200])]
    rt.dispatch(s,o)
    assert live.pending(rt.db,s["id"])["stage"]=="UNKNOWN"
    assert rt.db.load()["cash"]==100 and not rt.db.load()["positions"]
    assert rt.db.db.execute("select count(*) from venue_executions").fetchone()[0]==0
    rt.db.db.close()

def test_paused_by_order_lane_during_scan_stays_paused(tmp_path):
    rt=Runtime(tmp_path);s=exchange_session(rt)
    v=Mock();rt.venue=lambda c:v
    v.audit.return_value={"dedicated_balance_match":True}
    def interrupted(c,t):
        with rt.lock,rt.db.db:
            cur=rt.db.load()
            cur.update(lifecycle_status="PAUSED",needs_check=True,admitted=False)
            rt.db.save(cur)
        return historical(START)
    rt.feed=interrupted
    rt.tick()
    assert rt.db.load()["lifecycle_status"]=="PAUSED" and not live.pending(rt.db,s["id"])
    rt.db.db.close()


def test_legacy_pending_requires_explicit_binding_and_original_receipt(tmp_path):
    rt=Runtime(tmp_path);s=exchange_session(rt)
    with rt.db.db:
        live.enqueue(rt.db,s,"BTC","BUY",{"time":int(time.time()),"price":10},20,"fixture")
        o=live.pending(rt.db,s["id"])
        o.pop("account_ref");s.pop("account_ref")
        o["prepared"]={"quantity":2,"price":10,"contract":1}
        live.save(rt.db,o,"SENDING");rt.db.save(s)
    v=Mock();rt.venue=lambda c:v;v.pair.return_value="BTC/USDT"
    rt.dispatch(s,o)
    v.lookup.assert_not_called()
    with rt.db.db:
        with pytest.raises(ValueError,match="确认绑定"):
            rt.command(s["id"],"reconcile")
        rt.command(s["id"],"reconcile","核对原账户")
    v.lookup.return_value=dict(id="old",clientOrderId=o["client_id"],symbol="BTC/USDT",side="buy",
                               amount=2,status="expired",filled=0)
    rt.dispatch(rt.db.load(),live.pending(rt.db,s["id"]))
    assert not live.pending(rt.db,s["id"]) and rt.db.load()["account_ref"]==rt.account_ref(s["config"])
    v.submit.assert_not_called()
    rt.db.db.close()
