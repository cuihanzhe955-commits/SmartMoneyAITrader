"""Synthetic markets and ModelMock: never evidence of 100 public/live rounds."""
import copy,json,threading
from datetime import datetime,timezone
from uuid import uuid4
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
from ai.brain import Brain
from events.lab import EventLab,RoundRequest
from challenge.prediction import PredictionChallenges,PredictionConfig
from market.event_costs import estimate_cost
from market.event_details import resolution_evidence
from market.predictions import normalize,EventResearch,EventQuery
from test_event_research import market,NOW
from test_event_costs import info,depth


def system(tmp_path,**config):
    clock=[float(NOW)];brain=Brain(tmp_path/'terminal.db',clock=lambda:clock[0]);brain.setup()
    def metadata(mid):
        raw=market(str(mid));raw.update(version='v1',feesEnabled=True,endDate=datetime.fromtimestamp(NOW+50000,timezone.utc).isoformat())
        return normalize(raw,clock[0])
    class Details:
        def cost(self,q):
            m=metadata(q.market_id);raw=depth();curve=info()
            raw.update(market=m['condition_id'],asset_id=m['outcomes'][q.outcome_index]['token_id'],timestamp=str(int(clock[0]*1000)))
            curve['t']=[dict(t=o['token_id'],o=o['name']) for o in m['outcomes']]
            return estimate_cost(q,m,curve,raw,clock[0])
        def resolution(self,q):
            m=metadata(q.market_id);win=int(q.market_id)%2
            return resolution_evidence(dict(data=[dict(condition_id=m['condition_id'],status='resolved',payouts=[win*1000000,(1-win)*1000000],resolved_at=str(clock[0]-1),last_update_timestamp=str(clock[0]-1))]),m,clock[0])
    provider=Mock();provider.c=dict(model='ModelMock',timeout=5,calls=10000)
    def chat(prompt,context):
        if 'observation' in prompt:return json.dumps(dict(observation='合成结果',hypothesis='需要样本外验证',invalidation='未复现'))
        return json.dumps(dict(action='BUY',probability=.9,reason='合成假设',counter_evidence='未校准'))
    provider.chat.side_effect=chat
    lab=EventLab(brain,Details(),lambda:provider,clock=lambda:clock[0])
    discovery=Mock();discovery.run.side_effect=lambda _:dict(provider='polymarket',scanned=150,rows=[metadata(i) for i in range(1,151)])
    manager=PredictionChallenges(lab,discovery,clock=lambda:clock[0])
    c=PredictionConfig(request_id=str(uuid4()),capital=1000.,**config)
    cid=manager.create(c)['id']
    return manager,lab,cid,clock,provider,c


def one(manager,lab,cid,clock):
    manager.tick()
    for _ in range(3):
        lab.tick('work')
        row=manager.view(cid)['challenges'][0];sid=row['session_id']
        rounds=lab.view(sid)['rounds']
        if not rounds:
            # Discovery reserves its next retry before a lock-delayed enqueue.
            # Advance the synthetic fixture clock to that durable retry boundary.
            clock[0]=max(clock[0],row.get('next_scan',clock[0]))
            from ai.worker_policy import BrainBusy
            raise BrainBusy('fixture scheduling deferred by database contention')
        latest=rounds[0]
        if latest['status'] in ('WAITING','FAILED'):break
    manager.tick();clock[0]+=61;lab.tick('settle');lab.tick('work');manager.tick()


def test_100_rounds_model_mock_recovery_and_exact_statistics(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path)
    for i in range(100):
        one(m,lab,cid,clock)
        if i==49:m=PredictionChallenges(lab,m.discovery,clock=lambda:clock[0])
    final=m.view(cid)['challenges'][0];s=final['statistics']
    assert final['status']=='COMPLETED'
    assert s['valid_completed']==s['predicted']==s['participated']==s['settled']==100
    assert s['scheduled']==100 and s['failed']==s['cancelled']==0
    assert s['accuracy']==s['trade_win_rate']==.5
    assert s['longest_trade_win_streak']==s['longest_trade_loss_streak']==1
    assert provider.chat.call_count==200
    assert lab.reconcile(final['session_id'])['verified']
    m.tick();assert len(m.view(cid)['challenges'][0]['rounds'])==100


def test_rules_skip_completes_valid_rounds_without_ai_or_fake_fills(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path,rounds=3,engine='rules')
    for _ in range(3):one(m,lab,cid,clock)
    final=m.view(cid)['challenges'][0];s=final['statistics']
    assert final['status']=='COMPLETED' and s['valid_completed']==s['skipped']==3
    assert s['participated']==0 and s['trade_win_rate'] is None
    assert float(final['account']['cash'])==1000
    provider.chat.assert_not_called()


@pytest.mark.parametrize('crash_after_enqueue',[False,True])
def test_reservation_restart_never_creates_a_duplicate_round(tmp_path,crash_after_enqueue):
    m,lab,cid,clock,provider,c=system(tmp_path,rounds=1)
    original=lab.enqueue
    def crash(*args,**kwargs):
        if crash_after_enqueue:original(*args,**kwargs)
        raise KeyboardInterrupt()
    lab.enqueue=crash
    with pytest.raises(KeyboardInterrupt):m.tick()
    lab.enqueue=original
    recovered=PredictionChallenges(lab,m.discovery,clock=lambda:clock[0]);recovered.tick();recovered.tick()
    final=recovered.view(cid)['challenges'][0]
    assert len(final['rounds'])==1 and final['rounds'][0]['round_id']
    assert len(lab.view(final['session_id'])['rounds'])==1


def test_pause_resume_and_stop_preserve_pending_settlement(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path,rounds=3)
    m.tick();lab.tick('work');m.tick();m.command(cid,'pause')
    m.tick();assert len(m.view(cid)['challenges'][0]['rounds'])==1
    clock[0]+=61;lab.tick('settle');m.tick()
    assert m.view(cid)['challenges'][0]['status']=='PAUSED'
    m.command(cid,'resume');m.tick();lab.tick('work');lab.tick('work');m.tick()
    m.command(cid,'stop');assert m.view(cid)['challenges'][0]['status']=='STOPPING'
    clock[0]+=61;lab.tick('settle');m.tick()
    final=m.view(cid)['challenges'][0]
    assert final['status']=='STOPPED' and final['statistics']['valid_completed']==2
    assert lab.reconcile(final['session_id'])['verified']


def test_paused_history_does_not_starve_initialization_or_active_rounds(tmp_path):
    manager, lab, first, clock, _, config = system(tmp_path, rounds=2, engine='rules')
    manager.command(first, 'pause')
    for _ in range(50):
        paused = manager.create(config.model_copy(update={'request_id': str(uuid4())}))['id']
        manager.command(paused, 'pause')

    new_config = config.model_copy(update={'request_id': str(uuid4())})
    with patch.object(manager, '_initialize', side_effect=KeyboardInterrupt), pytest.raises(KeyboardInterrupt):
        manager.create(new_config)
    recovered = PredictionChallenges(lab, manager.discovery, clock=lambda: clock[0])
    recovered.tick()
    latest = recovered.view()['challenges'][0]
    assert latest['status'] == 'ACTIVE'
    cid = latest['id']
    recovered.tick()
    lab.tick('work')
    recovered.command(cid, 'pause')
    clock[0] += 61
    lab.tick('settle')
    recovered.tick()
    paused = recovered.view(cid)['challenges'][0]
    assert paused['status'] == 'PAUSED'
    assert paused['statistics']['scheduled'] == paused['statistics']['settled'] == 1
    recovered.command(cid, 'stop')
    assert recovered.view(cid)['challenges'][0]['status'] == 'STOPPED'
    recovered.command(first, 'resume')
    recovered.tick()
    assert recovered.view(first)['challenges'][0]['statistics']['scheduled'] == 1


def test_slow_fetch_cannot_resurrect_a_cancelled_round(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path)
    m.tick();started=threading.Event();release=threading.Event();original=lab.details.cost
    def slow(q):started.set();assert release.wait(3);return original(q)
    lab.details.cost=slow
    with ThreadPoolExecutor(max_workers=1) as pool:
        work=pool.submit(lab.tick,'work')
        try:
            assert started.wait(2);m.command(cid,'stop')
        finally:release.set()
        work.result(3)
    m.tick();final=m.view(cid)['challenges'][0]
    assert final['status']=='STOPPED' and final['statistics']['cancelled']==1
    assert final['statistics']['participated']==0
    assert lab.view(final['session_id'])['rounds'][0]['status']=='FAILED'
    provider.chat.assert_not_called()


@pytest.mark.parametrize('lane', ['discover', 'cost'])
def test_shutdown_drains_late_network_failure_before_reopening(tmp_path, lane):
    manager, lab, cid, _, _, _ = system(tmp_path)
    lab.challenges = manager
    entered, release = threading.Event(), threading.Event()
    def delayed(*_):
        entered.set()
        assert release.wait(5)
        raise ValueError('late failure')
    if lane == 'discover':
        manager.discovery.run.side_effect = delayed
    else:
        manager.tick()
        lab.details.cost = delayed
    lab.start()
    try:
        lab.start()
        assert entered.wait(3)
        before = manager.view(cid)['challenges'][0]
        with ThreadPoolExecutor(max_workers=1) as pool:
            shutdown = pool.submit(lab.close)
            assert lab.stop.wait(1)
            assert not shutdown.done()
            release.set()
            shutdown.result(3)
        assert not any(t.is_alive() for t in lab.threads + [manager.thread])
        after = manager.view(cid)['challenges'][0]
        assert after['statistics'] == before['statistics'] and after['detail'] == before['detail']
        assert not manager.error and not lab.error
        lab.close(); lab.start()
        assert not any(t.is_alive() for t in lab.threads + [manager.thread])
    finally:
        release.set()
        lab.close()


def test_second_service_cannot_recover_rows_while_first_owns_ledger(tmp_path):
    from fastapi.testclient import TestClient
    from terminal.api import create_app
    with TestClient(create_app(tmp_path)):
        with patch('terminal.api.Runtime') as runtime:
            with pytest.raises(OSError), TestClient(create_app(tmp_path)):
                pass
            runtime.assert_not_called()


def test_late_fetch_error_cannot_resurrect_cancelled_round(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path);m.tick()
    def cancelled(_):
        m.command(cid,'stop')
        raise ValueError('late network timeout')
    lab.details.cost=cancelled;lab.tick('work');m.tick()
    final=m.view(cid)['challenges'][0]
    assert final['status']=='STOPPED'
    assert lab.view(final['session_id'])['rounds'][0]['status']=='FAILED'
    assert lab.reconcile(final['session_id'])['verified']


def test_missing_ai_config_does_not_create_a_phantom_challenge(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path);m.command(cid,'pause')
    lab.provider_factory=Mock(side_effect=ValueError('请先配置AI'))
    with pytest.raises(ValueError,match='配置AI'):m.create(c.model_copy(update={'request_id':str(uuid4())}))
    assert len(m.view()['challenges'])==1


def test_unknown_results_do_not_count_as_completed_or_realized(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path,rounds=1)
    m.tick();lab.tick('work');lab.details.resolution=Mock(return_value=dict(settlement_verified=False,status='proposed'))
    clock[0]+=61;lab.tick('settle');m.tick()
    result=m.view(cid)['challenges'][0]
    assert result['status']=='ACTIVE' and result['statistics']['valid_completed']==0
    assert result['statistics']['reference_realized']==0 and result['statistics']['waiting']==1
    stats = result['statistics']
    assert stats['open_positions'] == 1 and stats['accuracy'] is None and stats['trade_win_rate'] is None
    assert float(result['account']['cash']) + stats['open_reference_cost'] == pytest.approx(c.capital)


def test_fractional_and_neutral_forecasts_have_separate_scoring_denominators():
    rows = []
    for ordinal, (p, payout, realized) in enumerate([(.9, .5, -2), (.5, 0, -4), (.7, 1, 3)]):
        receipt = dict(status='SETTLED', valid_prediction=True, probability=p, payout=payout,
                       participated=True, realized=realized, round_id=str(ordinal), settled_at=ordinal)
        rows.append(dict(receipt=receipt, observed_status='SETTLED', cancelled=False))
    stats = PredictionChallenges.stats(rows, 100)
    assert stats['accuracy_samples'] == stats['fractional_results'] == 1
    assert stats['accuracy'] == 1 and stats['trade_win_rate'] == pytest.approx(1 / 3)
    assert stats['reference_realized'] == -3 and stats['max_cost_basis_drawdown_pct'] == 6


def test_no_candidates_and_source_failure_are_bounded_not_fake_rounds(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path)
    m.discovery.run.return_value=dict(provider='polymarket',scanned=0,rows=[]);m.discovery.run.side_effect=None
    m.tick();m.tick();assert m.discovery.run.call_count==1
    assert m.view(cid)['challenges'][0]['statistics']['scheduled']==0
    clock[0]+=31;m.discovery.run.side_effect=ValueError('公开接口限频');m.tick();m.tick()
    assert m.discovery.run.call_count==2
    assert m.view(cid)['challenges'][0]['statistics']['predicted']==0


def test_model_failure_pauses_and_resume_uses_new_condition(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path,rounds=1)
    original=provider.chat.side_effect;provider.chat.side_effect=ValueError('AI预算已用完')
    m.tick();lab.tick('work');m.tick()
    assert m.view(cid)['challenges'][0]['status']=='PAUSED'
    assert m.view(cid)['challenges'][0]['statistics']['predicted']==0
    provider.chat.side_effect=original;m.command(cid,'resume');one(m,lab,cid,clock)
    final=m.view(cid)['challenges'][0]
    assert final['status']=='COMPLETED' and final['statistics']['failed']==1
    assert [r['condition_id'] for r in final['rounds']]==['0x'+f'{i:064x}' for i in (1,2)]


def test_owned_session_rejects_manual_round_injection_and_early_close(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path)
    sid=m.view(cid)['challenges'][0]['session_id']
    with pytest.raises(ValueError):lab.enqueue(RoundRequest(session_id=sid,request_id=str(uuid4()),market_id='1'))
    with pytest.raises(ValueError):lab.command(sid,'end')
    lab.provider_factory=Mock(side_effect=ValueError('AI配置暂不可用'))
    assert m.create(c)['duplicate']
    with pytest.raises(ValueError):m.create(c.model_copy(update={'name':'changed'}))
    with pytest.raises(ValueError):m.create(c.model_copy(update={'request_id':str(uuid4())}))


def test_market_precheck_failures_pause_after_threshold_without_counting_goal(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path,max_consecutive_failures=2)
    lab.details.cost=Mock(side_effect=ValueError('盘口过期'))
    for _ in range(2):
        m.tick();lab.tick('work');m.tick();clock[0]+=31
    final=m.view(cid)['challenges'][0]
    assert final['status']=='PAUSED' and final['statistics']['failed']==2
    assert final['statistics']['valid_completed']==0
    provider.chat.assert_not_called()


def test_future_or_unsupported_candidates_are_not_scheduled(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path)
    rows=copy.deepcopy(m.discovery.run(None)['rows'][:3])
    rows[0]['protocol_version']='v2';rows[1]['ends_at']=NOW-1;rows[2]['ends_at']=NOW+24*3600+1
    m.discovery.run.side_effect=None;m.discovery.run.return_value=dict(provider='polymarket',rows=rows,scanned=3)
    m.tick();assert m.view(cid)['challenges'][0]['statistics']['scheduled']==0


def test_scheduled_condition_change_is_rejected_before_prediction(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path)
    original=lab.details.cost
    def changed(q):
        snap=original(q);snap['condition_id']='0x'+'f'*64;return snap
    lab.details.cost=changed;m.tick();lab.tick('work');m.tick()
    final=m.view(cid)['challenges'][0]
    assert final['statistics']['participated']==final['statistics']['predicted']==0
    assert final['statistics']['failed']==1
    provider.chat.assert_not_called()


def test_loss_breaker_pauses_and_cannot_be_bypassed_by_resume(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path,rounds=3,max_loss_pct=.1)
    def losing(q):
        meta=normalize(market(q.market_id),clock[0])
        return resolution_evidence(dict(data=[dict(condition_id=meta['condition_id'],status='resolved',payouts=[0,1000000],resolved_at=str(clock[0]-1),last_update_timestamp=str(clock[0]-1))]),meta,clock[0])
    lab.details.resolution=losing
    one(m,lab,cid,clock)
    final=m.view(cid)['challenges'][0]
    assert final['status']=='PAUSED' and final['statistics']['participated']==1
    assert final['statistics']['reference_realized']<0
    with pytest.raises(ValueError,match='亏损阈值'):m.command(cid,'resume')
    assert lab.reconcile(final['session_id'])['verified']


def test_upcoming_query_uses_documented_end_filter_and_separate_cache():
    fetch=Mock(return_value=[]);service=EventResearch(fetch=fetch,clock=lambda:NOW)
    service.run(EventQuery(upcoming_only=True));params=fetch.call_args.args[0]
    assert params['order']=='endDate' and params['ascending']=='true' and 'end_date_min' in params
    service.run(EventQuery());assert fetch.call_count==2
    with pytest.raises(ValueError):service.run(EventQuery(upcoming_only=True,lifecycle='closed'))


def test_api_owns_session_and_never_changes_spot_runtime(tmp_path):
    from fastapi.testclient import TestClient
    from terminal.api import create_app
    app=create_app(tmp_path)
    with TestClient(app) as client:
        manager=app.state.event_lab.challenges
        manager.discovery.run=Mock(return_value=dict(provider='polymarket',scanned=0,rows=[]))
        before=client.get('/api/state').json()
        body=dict(request_id=str(uuid4()),engine='rules',rounds=2)
        result=client.post('/api/research/challenges',json=body)
        assert result.status_code==200,result.text
        cid=result.json()['id']
        sid=manager.view(cid)['challenges'][0]['session_id']
        assert client.post('/api/research/lab/rounds',json=dict(session_id=sid,request_id=str(uuid4()),market_id='1')).status_code==400
        assert client.post('/api/research/challenges/command',json=dict(id=cid,action='pause')).status_code==200
        report=client.get('/api/research/challenges/report?id='+cid).json()
        assert report['reconciliation']['verified'] and not report['execution_enabled']
        assert not report['notification_verified']
        assert client.post('/api/research/challenges',json=dict(request_id=str(uuid4()),execution='live')).status_code==422
        assert client.get('/api/state').json()==before


def test_legacy_f_round_retry_is_normalized_without_reenqueue(tmp_path):
    m,lab,cid,clock,provider,c=system(tmp_path)
    # Independent old F session, before expected_condition_id existed.
    from events.lab import LabConfig
    sid=lab.create(LabConfig(request_id=str(uuid4())))['id']
    q=RoundRequest(session_id=sid,request_id=str(uuid4()),market_id='1')
    rid=lab.enqueue(q)['id']
    with lab.brain.db(True) as db:
        old=json.loads(db.execute('SELECT inputs FROM event_lab_rounds WHERE id=?',(rid,)).fetchone()[0]);old.pop('expected_condition_id');old['shares']=10
        db.execute('UPDATE event_lab_rounds SET inputs=? WHERE id=?',(json.dumps(old),rid))
    assert lab.enqueue(q)==dict(id=rid,duplicate=True)


@pytest.mark.parametrize('resolved_offset', [5, 10])
def test_resolution_known_before_model_finishes_is_not_counted_as_success(tmp_path, resolved_offset):
    m,lab,cid,clock,provider,c=system(tmp_path)
    original=provider.chat.side_effect
    def slow(prompt,data):clock[0]+=10;return original(prompt,data)
    provider.chat.side_effect=slow
    m.tick();lab.tick('work')
    def early(q):
        meta=normalize(market(q.market_id),clock[0])
        return resolution_evidence(dict(data=[dict(condition_id=meta['condition_id'],status='resolved',payouts=[1000000,0],resolved_at=str(NOW+resolved_offset),last_update_timestamp=str(clock[0]))]),meta,clock[0])
    sid = m.view(cid)['challenges'][0]['session_id']
    with lab.brain.db() as db:
        stale = db.execute("SELECT * FROM event_lab_rounds WHERE session_id=?", (sid,)).fetchone()
    m.command(cid, 'stop')
    m = PredictionChallenges(lab, m.discovery, clock=lambda: clock[0])
    lab.details.resolution = Mock(side_effect=TimeoutError())
    clock[0] += 61
    lab.tick('settle'); m.tick()
    assert m.view(cid)['challenges'][0]['status'] == 'STOPPING'
    lab.details.resolution=early;clock[0]+=61;lab.tick('settle');m.tick()
    final=m.view(cid)['challenges'][0]
    assert final['status'] == 'STOPPED'
    assert final['statistics']['failed'] == 1 and final['statistics']['predicted'] == 0
    assert final['statistics']['refunded'] == 1 and final['statistics']['open_reference_cost'] == 0
    lab.settle(stale)
    with lab.brain.db() as db:
        entries = dict(db.execute('SELECT kind,amount FROM event_lab_cash WHERE round_id=?', (stale['id'],)))
    assert set(entries) == {'DEBIT', 'REFUND'}
    assert lab.reconcile(sid)['verified'] and float(final['account']['cash']) == 1000
    assert final['statistics']['settled']==final['statistics']['valid_completed']==0
    assert '早于预测完成' in final['rounds'][0]['receipt']['error']


@pytest.mark.parametrize('data',[dict(rounds=0),dict(rounds=True),dict(capital=float('nan')),dict(scan_interval_sec=0),dict(execution='live'),dict(request_id='-'*36)])
def test_bad_or_live_config_is_rejected(data):
    with pytest.raises(ValidationError):PredictionConfig(**dict({'request_id':str(uuid4())},**data))

def test_worker_survives_scan_failure_and_retries(tmp_path):
    manager,lab,cid,*_=system(tmp_path)
    retried=threading.Event()
    def tick():
        if not retried.is_set():
            retried.set()
            raise __import__('ai.worker_policy', fromlist=['BrainBusy']).BrainBusy('synthetic busy database')
        manager.stop.set()
    with patch.object(manager,'tick',side_effect=tick):
        manager.start()
        manager.thread.join(timeout=5)
        assert retried.is_set()
        assert manager.stop.is_set(), 'worker died instead of retrying after database failure'
        assert '退避重试' in manager.error
    manager.close()
