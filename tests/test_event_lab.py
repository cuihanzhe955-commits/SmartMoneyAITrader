import json
import copy
import threading
from uuid import uuid4
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
from ai.brain import Brain, BrainSettings
from events.lab import EventLab, LabConfig, RoundRequest
from events.evaluation import evaluate
from market.event_details import resolution_evidence
from test_event_costs import service,metadata
from test_event_details import resolved
from test_event_research import NOW


def lab(tmp_path,engine="ai",**cfg):
    clock=[NOW];brain=Brain(tmp_path/"terminal.db",clock=lambda:clock[0]);brain.setup()
    details=service();details.clock=lambda:clock[0]
    data=resolved();data["data"][0].update(resolved_at=str(NOW+10),last_update_timestamp=str(NOW+10))
    details.resolution=Mock(side_effect=lambda _:resolution_evidence(data,metadata(),clock[0]))
    provider=Mock();provider.c=dict(model="fixture-model",timeout=5,calls=100)
    provider.chat=Mock(return_value=json.dumps(dict(action="BUY",probability=.9,reason="合成研究假设",counter_evidence="未校准")))
    obj=EventLab(brain,details,lambda:provider,clock=lambda:clock[0])
    config=LabConfig(request_id=str(uuid4()),engine=engine,**cfg)
    sid=obj.create(config)["id"]
    return obj,sid,clock,provider,data


def enqueue(obj,sid,**kw):
    q=RoundRequest(session_id=sid,request_id=str(uuid4()),market_id="1",**kw)
    return q,obj.enqueue(q)["id"]


def test_reference_paper_full_lifecycle_debit_settlement_reflection_and_restart(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    q,rid=enqueue(obj,sid);obj.tick()
    row=obj.view(sid)["rounds"][0];d=row["data"]
    assert row["status"]=="WAITING" and d["action"]=="REFERENCE_BUY"
    assert d["order"]["id"].startswith("REFERENCE_PAPER_") and not d["order"]["actual_order"]
    assert obj.brain.search()["total"]==1
    assert obj.enqueue(q)["duplicate"]
    clock[0]+=100;obj.tick();obj.tick()
    report=evaluate(obj,sid);assert report["actual"]["participated"]==report["actual"]["settled"]==1
    assert report["actual"]["reference_realized"]>0
    # A malformed reflection never overwrites valid cash settlement evidence.
    assert obj.view(sid)["rounds"][0]["status"]=="SETTLED"
    before=obj.view(sid)["sessions"][0]["cash"]
    restored=EventLab(obj.brain,obj.details,lambda:provider,clock=lambda:clock[0]);restored.tick()
    assert restored.view(sid)["sessions"][0]["cash"]==before
    with obj.brain.db() as db:assert db.execute("SELECT COUNT(*) FROM event_lab_cash").fetchone()[0]==2


def test_rules_without_key_records_skip_no_fake_order(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path,engine="rules")
    enqueue(obj,sid);obj.tick()
    d=obj.view(sid)["rounds"][0]["data"]
    assert d["action"]=="SKIP" and d["order"] is None
    provider.chat.assert_not_called()
    clock[0]+=100;obj.tick();obj.tick()
    r=evaluate(obj,sid);assert r["actual"]["settled"]==1 and r["actual"]["participated"]==0
    assert r["actual"]["reference_cash"]==100


@pytest.mark.parametrize("mutation",["stale","unknown_end","ended","wrong_condition","wrong_token","resolved_before_prediction"])
def test_invalid_time_identity_or_result_never_creates_a_false_settlement(tmp_path,mutation):
    obj,sid,clock,provider,data=lab(tmp_path)
    if mutation in ("stale","unknown_end","ended"):
        snap=obj.details.cost(RoundRequest(session_id=sid,request_id=str(uuid4()),market_id="1"))
        if mutation=="stale":snap["source_timestamp"]=NOW-30
        else:snap["market_ends_at"]=None if mutation=="unknown_end" else NOW
        obj.details.cost=Mock(return_value=snap)
    enqueue(obj,sid);obj.tick()
    if mutation in ("stale","unknown_end","ended"):
        assert obj.view(sid)["rounds"][0]["status"]=="FAILED";provider.chat.assert_not_called();return
    clock[0]+=100
    evidence=resolution_evidence(data,metadata(),clock[0])
    if mutation=="wrong_condition":evidence["condition_id"]="0x"+"f"*64
    if mutation=="wrong_token":evidence["payouts"][0]["token_id"]="999"
    if mutation=="resolved_before_prediction":evidence["resolved_at"]=NOW-1
    obj.details.resolution.return_value=evidence;obj.details.resolution.side_effect=None
    obj.tick()
    assert obj.view(sid)["rounds"][0]["status"]=="WAITING"
    with obj.brain.db() as db:assert db.execute("SELECT COUNT(*) FROM event_lab_cash WHERE kind='PAYOUT'").fetchone()[0]==0


def test_timeout_or_bad_schema_is_skip_and_no_retry_order(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    provider.chat.return_value='{"action":"BUY","probability":2}'
    q,_=enqueue(obj,sid);obj.tick();obj.enqueue(q);obj.tick()
    assert obj.view(sid)["rounds"][0]["status"]=="FAILED"
    with obj.brain.db() as db:assert db.execute("SELECT COUNT(*) FROM event_lab_cash").fetchone()[0]==0


def test_late_model_response_is_not_executed_or_scored(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    answer=provider.chat.return_value
    def late(*_):clock[0]+=31;return answer
    provider.chat.side_effect=late
    enqueue(obj,sid);obj.tick();d=obj.view(sid)["rounds"][0]["data"]
    assert d["action"]=="SKIP" and d["forecasts"]["selected"]["probability"] is None


def test_same_condition_position_and_budget_isolation(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path,capital=10.,per_trade=10.)
    enqueue(obj,sid);obj.tick();enqueue(obj,sid);obj.tick("work")
    rows=obj.view(sid)["rounds"]
    assert sum(bool(r["data"].get("order")) for r in rows)==1
    assert float(obj.view(sid)["sessions"][0]["cash"])>=0
    second=obj.create(LabConfig(request_id=str(uuid4()),capital=20.))["id"]
    assert next(s for s in obj.view()["sessions"] if s["id"]==second)["cash"]=="20.0"


def test_pause_blocks_new_prediction_but_not_official_settlement(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    enqueue(obj,sid);obj.tick();obj.command(sid,"pause")
    with pytest.raises(ValueError):enqueue(obj,sid)
    clock[0]+=100;obj.tick("settle")
    assert obj.view(sid)["rounds"][0]["status"]=="SETTLED"
    obj.command(sid,"end")


def test_settlement_lane_continues_while_another_model_call_blocks(tmp_path):
    obj,sid,clock,provider,data=lab(tmp_path)
    enqueue(obj,sid);obj.tick()
    second=obj.create(LabConfig(request_id=str(uuid4()),engine="ai"))["id"]
    # Keep new snapshot fresh while first result becomes available.
    clock[0]+=20;snap=obj.details.cost(RoundRequest(session_id=sid,request_id=str(uuid4()),market_id="1"));snap["source_timestamp"]=clock[0]
    obj.details.cost=Mock(return_value=snap)
    started=threading.Event();release=threading.Event();answer=provider.chat.return_value
    def blocked(*_):started.set();assert release.wait(3);return answer
    provider.chat.side_effect=blocked;enqueue(obj,second)
    with ThreadPoolExecutor(max_workers=1) as pool:
        work=pool.submit(obj.tick,"work")
        try:
            assert started.wait(2);obj.tick("settle")
            assert obj.view(sid)["rounds"][0]["status"]=="SETTLED"
        finally:release.set()
        work.result(timeout=3)


def test_paired_scoring_uses_same_snapshot_and_no_unsettled_profit(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path,paired_evaluation=True,use_memory=True)
    obj.brain.settings(BrainSettings(retrieval=True))
    obj.brain.put("event:"+sid,"past","reflection",{"fact":"past"},NOW-10,available_at=NOW-5)
    obj.brain.put("event:"+sid,"future","reflection",{"fact":"future"},NOW+1,available_at=NOW+2)
    enqueue(obj,sid);obj.tick()
    calls=provider.chat.call_args_list
    assert calls[0].args[1]["snapshot"]==calls[1].args[1]["snapshot"]
    assert not calls[0].args[1]["memories"] and len(calls[1].args[1]["memories"])==1
    assert evaluate(obj,sid)["paired_rounds"]==0
    clock[0]+=100;obj.tick("settle")
    report=evaluate(obj,sid)
    assert report["paired_rounds"]==1
    assert report["variants"]["with_memory"]["brier"]==pytest.approx(.01)
    assert report["variants"]["with_memory"]["reference_net"]==report["variants"]["without_memory"]["reference_net"]


def test_reflection_schema_and_hypothesis_never_change_risk(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    enqueue(obj,sid);obj.tick();clock[0]+=100;obj.tick("settle")
    provider.chat.return_value=json.dumps(dict(observation="结果吻合",hypothesis="需要更多样本",invalidation="样本外失效"))
    obj.tick("work")
    memories=obj.brain.search()["rows"]
    assert any(m["status"]=="hypothesis" for m in memories)
    assert any(m["status"]=="confirmed_result" for m in memories)
    assert obj.view(sid)["sessions"][0]["config"]["max_loss_pct"]==30


def test_invalid_config_and_real_execution_fields_are_rejected():
    with pytest.raises(ValidationError):LabConfig(request_id=str(uuid4()),execution="live")
    with pytest.raises(ValidationError):LabConfig(request_id=str(uuid4()),capital=float("nan"))


def test_cash_drift_blocks_prediction_and_does_not_reset_database(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    with obj.brain.db(True) as db:
        r=db.execute("SELECT state FROM event_lab_sessions WHERE id=?",(sid,)).fetchone();s=json.loads(r[0]);s['cash']='1000'
        db.execute("UPDATE event_lab_sessions SET state=? WHERE id=?",(json.dumps(s),sid))
    enqueue(obj,sid);obj.tick()
    assert obj.view(sid)['rounds'][0]['status']=='FAILED'
    with pytest.raises(ValueError,match='账本'):obj.reconcile(sid)
    assert obj.view(sid)['sessions'][0]['cash']=='1000'


def test_unresolved_and_fractional_outcomes_keep_balances_correct(tmp_path):
    obj,sid,clock,provider,data=lab(tmp_path)
    enqueue(obj,sid);obj.tick();clock[0]+=100
    data['data'][0]['status']='proposed';obj.tick('settle')
    assert obj.view(sid)['rounds'][0]['status']=='WAITING'
    assert evaluate(obj,sid)['actual']['reference_realized']==0
    data['data'][0].update(status='resolved',payouts=[500000,500000]);clock[0]+=61;obj.tick('settle')
    row=obj.view(sid)['rounds'][0]
    assert row['status']=='SETTLED' and row['data']['payout']==.5
    assert obj.reconcile(sid)['verified']


def test_ai_budget_and_model_change_do_not_submit_paper_orders(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path,paired_evaluation=True)
    provider.c['calls']=1
    enqueue(obj,sid);obj.tick()
    assert obj.view(sid)['rounds'][0]['status']=='FAILED'
    assert obj.view(sid)['sessions'][0]['calls']==1
    assert float(obj.reconcile(sid)['cash'])==100


def test_resume_durable_predicting_round_rejects_stale_source(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    def interrupt(*_):raise KeyboardInterrupt()
    provider.chat.side_effect=interrupt;enqueue(obj,sid)
    with pytest.raises(KeyboardInterrupt):obj.tick()
    assert obj.view(sid)['rounds'][0]['status']=='PREDICTING'
    clock[0]+=100;provider.chat.side_effect=None
    restarted=EventLab(obj.brain,obj.details,lambda:provider,clock=lambda:clock[0]);restarted.tick()
    row=restarted.view(sid)['rounds'][0]
    assert row['data']['action']=='SKIP' and row['data']['order'] is None


def test_transaction_failure_cannot_half_debit_a_reference_order(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    with obj.brain.db(True) as db:db.execute("CREATE TRIGGER fail_debit BEFORE INSERT ON event_lab_cash BEGIN SELECT RAISE(ABORT,'fixture'); END")
    enqueue(obj,sid);obj.tick()
    assert float(obj.view(sid)['sessions'][0]['cash'])==100
    assert obj.view(sid)['rounds'][0]['data']['order'] is None
    assert obj.reconcile(sid)['verified']


def test_shutdown_cancels_late_model_write(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path);answer=provider.chat.return_value
    provider.chat.side_effect=lambda *_:(obj.close() or answer)
    enqueue(obj,sid);obj.tick()
    assert obj.view(sid)['rounds'][0]['status']=='PREDICTING'
    assert float(obj.reconcile(sid)['cash'])==100


def test_actual_api_lab_routes_cannot_change_live_runtime(tmp_path):
    from fastapi.testclient import TestClient
    from terminal.api import create_app
    app=create_app(tmp_path)
    with TestClient(app) as c:
        before=c.get('/api/state').json()
        result=c.post('/api/research/lab/sessions',json=dict(request_id=str(uuid4()),name='合成API验收',capital=10.,per_trade=5.)).json()
        sid=result['id']
        assert c.post('/api/research/lab/command',json=dict(session_id=sid,action='pause')).status_code==200
        r=c.get('/api/research/lab/evaluation?session_id='+sid)
        assert r.status_code==200 and r.json()['reconciliation']['verified']
        assert c.post('/api/research/lab/sessions',json=dict(request_id=str(uuid4()),execution='live')).status_code==422
        assert c.get('/api/state').json()==before


def test_paired_model_switch_is_rejected_instead_of_mixing_samples(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path,paired_evaluation=True)
    changed=Mock();changed.c=dict(provider.c,model='different-model');changed.chat.return_value=provider.chat.return_value
    obj.provider_factory=Mock(side_effect=[provider,changed])
    enqueue(obj,sid);obj.tick()
    row=obj.view(sid)['rounds'][0]
    assert row['status']=='FAILED' and '模型发生变更' in row['data']['error']
    assert obj.reconcile(sid)['verified']


def test_paused_learning_does_not_make_api_calls_and_can_resume(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    enqueue(obj,sid);obj.tick();clock[0]+=100;obj.tick('settle')
    obj.brain.settings(BrainSettings(enabled=False));calls=provider.chat.call_count;obj.tick('work')
    assert provider.chat.call_count==calls
    obj.brain.settings(BrainSettings())
    provider.chat.return_value=json.dumps(dict(observation='result',hypothesis='test further',invalidation='fails out of sample'))
    obj.tick('work');assert any(m['status']=='hypothesis' for m in obj.brain.search()['rows'])


def test_concurrent_round_requests_are_durable_idempotent(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    q=RoundRequest(session_id=sid,request_id=str(uuid4()),market_id='1')
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:obj.enqueue(q),range(2)))
    assert results[0]['id']==results[1]['id']
    assert len(obj.view(sid)['rounds'])==1


def test_settlement_snapshot_corruption_retains_unresolved_order(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path)
    enqueue(obj,sid);obj.tick();clock[0]+=100
    with obj.brain.db(True) as db:
        row=db.execute('SELECT * FROM event_lab_rounds').fetchone();data=json.loads(row['data']);data['snapshot']['token_id']='999'
        db.execute('UPDATE event_lab_rounds SET data=? WHERE id=?',(json.dumps(data),row['id']))
    obj.tick('settle')
    assert obj.view(sid)['rounds'][0]['status']=='WAITING'
    assert obj.details.resolution.call_count==0


def test_replay_evidence_is_local_and_not_repeated_in_model_context(tmp_path):
    from events.adapters import PolymarketResearchAdapter,GateEventAdapter
    obj,sid,clock,provider,_=lab(tmp_path)
    _,rid=enqueue(obj,sid);obj.tick()
    full=obj.evidence(rid)
    assert 'replay_input' in full['data']['snapshot']
    assert 'replay_input' not in obj.view(sid)['rounds'][0]['data']['snapshot']
    assert 'replay_input' not in provider.chat.call_args.args[1]['snapshot']
    for adapter in (GateEventAdapter(),PolymarketResearchAdapter(Mock(),obj.details)):
        with pytest.raises(ValueError):adapter.submit_order({'mode':'live'})
        with pytest.raises(ValueError):adapter.cancel_order('not-an-order')
    gate=GateEventAdapter();assert not gate.capabilities()['enabled']
    with pytest.raises(ValueError):gate.list_ledger()


def test_learning_failure_does_not_postpone_settlement(tmp_path):
    obj,sid,clock,provider,_=lab(tmp_path);obj.brain.put=Mock(side_effect=ValueError('memory unavailable'))
    enqueue(obj,sid);obj.tick()
    assert obj.view(sid)['rounds'][0]['next_check']==NOW
    clock[0]+=100;obj.tick('settle')
    assert obj.view(sid)['rounds'][0]['status']=='SETTLED' and obj.reconcile(sid)['verified']


def test_optional_lab_initialization_failure_does_not_block_core_and_can_retry(tmp_path):
    from fastapi.testclient import TestClient
    from terminal.api import create_app
    from unittest.mock import patch
    original=EventLab;attempts=[0]
    def flaky(*args,**kwargs):
        attempts[0]+=1
        if attempts[0]==1:raise ValueError('optional research unavailable')
        return original(*args,**kwargs)
    with patch('terminal.api.EventLab',side_effect=flaky),TestClient(create_app(tmp_path)) as c:
        assert c.get('/api/health').status_code==200
        assert c.get('/api/research/lab').status_code==400
        assert c.post('/api/research/lab/retry',json={}).status_code==200
        assert c.get('/api/research/lab').status_code==200
        assert c.get('/api/state').json()['state'] is None
