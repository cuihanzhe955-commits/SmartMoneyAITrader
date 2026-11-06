"""Durable, bounded automatic prediction challenges over the reference-paper lab."""
import json,math,threading,time
from uuid import UUID,uuid4,uuid5,NAMESPACE_URL
from pydantic import Field
from events.lab import LabConfig,RoundRequest,D
from events.observations import canonical
from market.predictions import EventQuery


class PredictionConfig(LabConfig):
    request_id: str = Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    name: str = Field(default="100轮预测研究",min_length=1,max_length=80)
    engine: str = Field(default="ai",pattern=r"^(ai|rules)$")
    rounds: int = Field(default=100,ge=1,le=1000)
    shares: float = Field(default=20,gt=0,le=1e6,allow_inf_nan=False)
    max_slippage_pct: float = Field(default=1,ge=0,le=100,allow_inf_nan=False)
    outcome_index: int = Field(default=0,ge=0,le=1)
    scan_interval_sec: int = Field(default=30,ge=15,le=86400)
    horizon_hours: float = Field(default=24,gt=0,le=8760,allow_inf_nan=False)
    max_consecutive_failures: int = Field(default=5,ge=1,le=50)
    market_query: EventQuery = Field(default_factory=lambda:EventQuery(limit=50,pages=3,upcoming_only=True))


class PredictionChallenges:
    def __init__(self,lab,discovery,clock=time.time):
        self.lab,self.brain,self.discovery,self.clock=lab,lab.brain,discovery,clock
        self.stop=threading.Event();self.mutex=threading.Lock();self.error=""
        with self.brain.db(True) as db:
            db.execute("CREATE TABLE IF NOT EXISTS prediction_challenges(id TEXT PRIMARY KEY,request_id TEXT UNIQUE,config TEXT,state TEXT)")
            db.execute("""CREATE TABLE IF NOT EXISTS prediction_challenge_rounds(
                challenge_id TEXT REFERENCES prediction_challenges(id),ordinal INTEGER,request_id TEXT UNIQUE,
                market_id TEXT,condition_id TEXT,market TEXT,round_id TEXT,
                observed_status TEXT NOT NULL DEFAULT 'RESERVED',receipt TEXT NOT NULL DEFAULT '{}',cancelled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(challenge_id,ordinal),UNIQUE(challenge_id,condition_id))""")

    def _initialize(self,cid):
        with self.brain.db() as db:
            row=db.execute('SELECT * FROM prediction_challenges WHERE id=?',(cid,)).fetchone()
        c=PredictionConfig(**json.loads(row['config']))
        cfg={key:getattr(c,key) for key in LabConfig.model_fields}
        cfg['request_id']=str(uuid5(NAMESPACE_URL,'smart-money-prediction:'+cid))
        sid=self.lab.create(LabConfig(**cfg),owner=cid)['id']
        with self.brain.db(True) as db:
            state=json.loads(db.execute('SELECT state FROM prediction_challenges WHERE id=?',(cid,)).fetchone()[0])
            if state['status']=='INITIALIZING':
                state.update(status='ACTIVE',session_id=sid,detail='等待首次公开市场扫描')
                db.execute('UPDATE prediction_challenges SET state=? WHERE id=?',(canonical(state),cid))
        return sid

    def create(self,config):
        if config.market_query.provider!='polymarket' or config.market_query.lifecycle!='open':raise ValueError('自动挑战仅支持Polymarket开放市场研究')
        if config.per_trade>config.capital:raise ValueError('单轮预算不能超过独立参考资金')
        body=canonical(config.model_dump())
        with self.brain.db(True) as db:
            old=db.execute('SELECT * FROM prediction_challenges WHERE request_id=?',(config.request_id,)).fetchone()
            if old:
                if old['config']!=body:raise ValueError('同一挑战创建请求不能改变配置')
                cid=old['id'];duplicate=True
            else:
                if db.execute("SELECT 1 FROM prediction_challenges WHERE json_extract(state,'$.status') IN ('INITIALIZING','ACTIVE','STOPPING')").fetchone():raise ValueError('已有运行或结束维护中的自动挑战，请先暂停或等待结束')
                if config.engine=='ai':
                    if self.lab.provider_factory is None:raise ValueError('请先配置AI服务，或选择规则基线')
                    self.lab.provider_factory()  # Local validation only; no network/model call.
                cid=uuid4().hex;duplicate=False
                state=dict(status='INITIALIZING',created_at=self.clock(),session_id=None,next_scan=0,detail='',execution_enabled=False,environment='reference_paper')
                db.execute('INSERT INTO prediction_challenges VALUES(?,?,?,?)',(cid,config.request_id,body,canonical(state)))
        self._initialize(cid)
        return dict(id=cid,duplicate=duplicate)

    def _sync(self,db,cid):
        rows=db.execute("""SELECT m.ordinal,r.* FROM prediction_challenge_rounds m JOIN event_lab_rounds r ON r.id=m.round_id
            WHERE m.challenge_id=? AND (m.observed_status!=r.status OR
                (m.observed_status='WAITING' AND COALESCE(json_extract(m.receipt,'$.error'),'')!=COALESCE(json_extract(r.data,'$.error'),'')))
            ORDER BY m.ordinal""",(cid,)).fetchall()
        for r in rows:
            d=json.loads(r['data']);snap=d.get('snapshot',{});f=d.get('forecasts',{}).get('selected',{})
            p=f.get('probability');valid=(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1
                and d.get('decision_at',math.inf)<d.get('expires_at',-math.inf))
            receipt=dict(round_id=r['id'],created_at=r['created_at'],status=r['status'],model=d.get('model'),action=d.get('action'),
                probability=p,valid_prediction=valid,source_timestamp=snap.get('source_timestamp'),decision_at=d.get('decision_at'),
                snapshot_sha256=d.get('snapshot_sha256'),market_id=snap.get('market_id'),condition_id=snap.get('condition_id'),outcome=snap.get('outcome'),
                participated=bool(d.get('order')),order=d.get('order'),payout=d.get('payout'),realized=d.get('realized'),
                official_resolved_at=d.get('settlement',{}).get('resolved_at'),settled_at=d.get('settled_at'),
                reason=d.get('risk_reasons',[]),error=d.get('error',''),has_snapshot=bool(snap))
            receipt.update(reference_cash_after_entry=d.get('reference_cash_after_entry'),
                reference_cash_after_settlement=d.get('reference_cash_after_settlement'),
                estimated_fee=snap.get('modeled_fee'),rounding_reserve=snap.get('rounding_reserve'),modeled_slippage_pct=snap.get('modeled_slippage_pct'))
            db.execute('UPDATE prediction_challenge_rounds SET observed_status=?,receipt=? WHERE challenge_id=? AND ordinal=?',
                (r['status'],canonical(receipt),cid,r['ordinal']))

    def _rows(self,db,cid):
        return [dict(r,market=json.loads(r['market']),receipt=json.loads(r['receipt'])) for r in db.execute(
            'SELECT * FROM prediction_challenge_rounds WHERE challenge_id=? ORDER BY ordinal',(cid,))]

    @staticmethod
    def stats(rows,capital):
        receipts=[r['receipt'] for r in rows];completed=[r for r in receipts if r.get('status')=='SETTLED' and r.get('valid_prediction')]
        predicted=[r for r in receipts if r.get('valid_prediction')]
        binary=[r for r in completed if r.get('payout') in (0,1) and r['probability']!=.5]
        correct=[(r['probability']>.5)==(r['payout']==1) for r in binary]
        trades=[r for r in completed if r.get('participated')]
        equity=peak=float(capital);dd=0.;wins=losses=max_win=max_loss=0
        for r in sorted(trades,key=lambda r:(r['settled_at'],r['round_id'])):
            pnl=float(r['realized']);equity+=pnl;peak=max(peak,equity);dd=max(dd,100*(peak-equity)/peak)
            wins=wins+1 if pnl>0 else 0;losses=losses+1 if pnl<0 else 0
            max_win=max(max_win,wins);max_loss=max(max_loss,losses)
        return dict(scheduled=len(rows),predicted=len(predicted),participated=sum(r.get('participated',False) for r in receipts),
            settled=sum(r.get('status')=='SETTLED' for r in receipts),valid_completed=len(completed),
            skipped=sum(r.get('action')=='SKIP' and r.get('valid_prediction',False) for r in receipts),
            failed=sum(r['observed_status']=='FAILED' and not r['cancelled'] for r in rows),cancelled=sum(bool(r['cancelled']) for r in rows),
            waiting=sum(r.get('status')=='WAITING' for r in receipts),
            accuracy=sum(correct)/len(correct) if correct else None,accuracy_samples=len(correct),
            trade_win_rate=sum(float(r['realized'])>0 for r in trades)/len(trades) if trades else None,
            trade_samples=len(trades),fractional_results=sum(r.get('payout') not in (0,1) for r in completed),
            longest_trade_win_streak=max_win,longest_trade_loss_streak=max_loss,
            reference_realized=sum(float(r['realized']) for r in trades),max_cost_basis_drawdown_pct=dd,
            equity_basis='cash plus open positions at cost; not mark-to-market')

    def _update(self,db,cid):
        row=db.execute('SELECT * FROM prediction_challenges WHERE id=?',(cid,)).fetchone();s=json.loads(row['state']);c=json.loads(row['config'])
        self._sync(db,cid);rows=self._rows(db,cid);stats=self.stats(rows,c['capital'])
        pending=any(not r['cancelled'] and r['observed_status'] not in ('SETTLED','FAILED') for r in rows)
        if s['status'] not in ('INITIALIZING','COMPLETED','STOPPED'):
            session=json.loads(db.execute('SELECT state FROM event_lab_sessions WHERE id=?',(s['session_id'],)).fetchone()[0])
            if session.get('challenge_owner')!=cid or session.get('environment')!='reference_paper':raise ValueError('挑战会话归属或环境不符')
            if s['status']=='STOPPING' and not pending:s.update(status='STOPPED',detail='挑战已结束，已有轮次维护完成');session['status']='CLOSED'
            elif stats['valid_completed']>=c['rounds'] and not pending:s.update(status='COMPLETED',detail='目标有效轮次已全部取得官方结果');session['status']='CLOSED'
            elif s['status']=='ACTIVE':
                last=rows[-1]['receipt'] if rows else {};unacknowledged=bool(rows and rows[-1]['ordinal']>s.get('acknowledged_ordinal',0))
                bad=unacknowledged and last.get('status')=='FAILED' and last.get('has_snapshot')
                streak=0
                for r in reversed(rows):
                    if r['ordinal']<=s.get('acknowledged_ordinal',0):break
                    if r['observed_status']=='FAILED':streak+=1
                    else:break
                if (bad or streak>=c['max_consecutive_failures'] or (unacknowledged and last.get('status') in ('WAITING','SETTLED') and not last.get('valid_prediction'))):
                    s.update(status='PAUSED',detail=last.get('error') or '预测未通过有效性检查，已暂停新轮次');session['status']='PAUSED'
                if D(session['realized'])<=-D(session['initial'])*D(c['max_loss_pct'])/100:
                    s.update(status='PAUSED',detail='达到研究累计亏损停机阈值');session['status']='PAUSED'
                elif last.get('status')=='WAITING' and last.get('error'):s['detail']=last['error']
            db.execute('UPDATE event_lab_sessions SET state=? WHERE id=?',(canonical(session),s['session_id']))
        s['statistics']=stats
        s['statistics_as_of']=self.clock()
        db.execute('UPDATE prediction_challenges SET state=? WHERE id=?',(canonical(s),cid))
        return s,rows

    def command(self,cid,action):
        if action not in ('pause','resume','stop'):raise ValueError('挑战命令无效')
        with self.brain.db(True) as db:
            row=db.execute('SELECT * FROM prediction_challenges WHERE id=?',(cid,)).fetchone()
            if not row:raise ValueError('预测挑战不存在')
            s=json.loads(row['state'])
            if s['status'] in ('INITIALIZING','COMPLETED','STOPPED','STOPPING'):raise ValueError('当前挑战状态不能执行此操作')
            if action=='resume' and db.execute("SELECT 1 FROM prediction_challenges WHERE id!=? AND json_extract(state,'$.status') IN ('INITIALIZING','ACTIVE','STOPPING')",(cid,)).fetchone():raise ValueError('已有其他自动挑战运行')
            session=json.loads(db.execute('SELECT state FROM event_lab_sessions WHERE id=?',(s['session_id'],)).fetchone()[0])
            config=json.loads(row['config'])
            if action=='resume' and D(session['realized'])<=-D(session['initial'])*D(config['max_loss_pct'])/100:raise ValueError('已达到研究亏损阈值，请保留报告后另建会话')
            s.update(status={'pause':'PAUSED','resume':'ACTIVE','stop':'STOPPING'}[action],detail='用户操作：'+action,next_scan=0)
            if action=='resume':s['acknowledged_ordinal']=db.execute('SELECT COUNT(*) FROM prediction_challenge_rounds WHERE challenge_id=?',(cid,)).fetchone()[0]
            session['status']='ACTIVE' if action=='resume' else 'PAUSED'
            if action=='stop':
                db.execute("UPDATE prediction_challenge_rounds SET cancelled=1 WHERE challenge_id=? AND round_id IN (SELECT id FROM event_lab_rounds WHERE status IN ('QUEUED','PREDICTING'))",(cid,))
                db.execute("UPDATE event_lab_rounds SET status='FAILED' WHERE session_id=? AND status IN ('QUEUED','PREDICTING')",(s['session_id'],))
                db.execute('UPDATE prediction_challenge_rounds SET cancelled=1 WHERE challenge_id=? AND round_id IS NULL',(cid,))
            db.execute('UPDATE event_lab_sessions SET state=? WHERE id=?',(canonical(session),s['session_id']))
            db.execute('UPDATE prediction_challenges SET state=? WHERE id=?',(canonical(s),cid))
            self._update(db,cid)
        return {'ok':True}

    def _dispatch(self,cid,mapping,sid,c):
        if self.stop.is_set():return
        request=RoundRequest(session_id=sid,request_id=mapping['request_id'],market_id=mapping['market_id'],
            expected_condition_id=mapping['condition_id'],outcome_index=c.outcome_index,shares=c.shares,budget=c.per_trade,max_slippage_pct=c.max_slippage_pct)
        rid=self.lab.enqueue(request,owner=cid)['id']
        with self.brain.db(True) as db:db.execute('UPDATE prediction_challenge_rounds SET round_id=? WHERE challenge_id=? AND ordinal=?',(rid,cid,mapping['ordinal']))

    def _advance(self,cid):
        with self.brain.db(True) as db:
            s,rows=self._update(db,cid)
            cfg=json.loads(db.execute('SELECT config FROM prediction_challenges WHERE id=?',(cid,)).fetchone()[0])
        c=PredictionConfig(**cfg)
        if s['status']=='INITIALIZING':self._initialize(cid);return
        if s['status']!='ACTIVE':return
        pending=[r for r in rows if not r['cancelled'] and r['observed_status'] not in ('SETTLED','FAILED')]
        if pending:
            if pending[0]['round_id'] is None:self._dispatch(cid,pending[0],s['session_id'],c)
            return
        if len(rows)>=1000:
            self.command(cid,'pause');raise ValueError('挑战已达1000次尝试上限，请保留报告后另建会话')
        if self.clock()<s['next_scan']:return
        # Reserve a discovery interval BEFORE network I/O; no tight-loop retry.
        with self.brain.db(True) as db:
            live=json.loads(db.execute('SELECT state FROM prediction_challenges WHERE id=?',(cid,)).fetchone()[0])
            if live['status']!='ACTIVE':return
            live.update(next_scan=self.clock()+c.scan_interval_sec,detail='正在读取有界公开候选样本')
            db.execute('UPDATE prediction_challenges SET state=? WHERE id=?',(canonical(live),cid))
        result=self.discovery.run(c.market_query)
        if self.stop.is_set():return
        if result.get('provider')!='polymarket':raise ValueError('发现结果平台不符')
        used={r['condition_id'] for r in rows};now=self.clock()
        candidates=[m for m in result['rows'] if m['metadata_active'] and m.get('protocol_version')=='v1'
            and type(m.get('ends_at')) in (int,float) and now+30<m['ends_at']<=now+c.horizon_hours*3600 and m['condition_id'] not in used]
        candidates.sort(key=lambda m:(m['ends_at'],int(m['market_id'])))
        with self.brain.db(True) as db:
            state=json.loads(db.execute('SELECT state FROM prediction_challenges WHERE id=?',(cid,)).fetchone()[0])
            if state['status']!='ACTIVE':return
            state.update(scanned=result.get('scanned',0),eligible=len(candidates),last_scan_at=now,
                detail='没有新的有效候选；将按扫描间隔重试' if not candidates else '已选择下一轮公开候选')
            db.execute('UPDATE prediction_challenges SET state=? WHERE id=?',(canonical(state),cid))
            if not candidates:return
            market=candidates[0];ordinal=len(rows)+1;request_id=str(uuid5(UUID(cid),str(ordinal)))
            db.execute('INSERT INTO prediction_challenge_rounds(challenge_id,ordinal,request_id,market_id,condition_id,market) VALUES(?,?,?,?,?,?)',
                (cid,ordinal,request_id,market['market_id'],market['condition_id'],canonical(market)))
        self._dispatch(cid,dict(ordinal=ordinal,request_id=request_id,market_id=market['market_id'],condition_id=market['condition_id']),s['session_id'],c)

    def tick(self):
        if not self.mutex.acquire(False):return
        try:
            if self.stop.is_set():return
            with self.brain.db() as db:rows=db.execute("SELECT id FROM prediction_challenges WHERE json_extract(state,'$.status') NOT IN ('COMPLETED','STOPPED') ORDER BY rowid LIMIT 50").fetchall()
            for row in rows:
                if self.stop.is_set():break
                try:self._advance(row['id']);self.error=''
                except Exception as err:
                    self.error=str(err)[:220] if type(err) is ValueError else '自动挑战暂不可用；原轮次保留'
                    try:
                        with self.brain.db(True) as db:
                            s=json.loads(db.execute('SELECT state FROM prediction_challenges WHERE id=?',(row['id'],)).fetchone()[0])
                            s.update(detail=self.error,next_scan=self.clock()+60)
                            db.execute('UPDATE prediction_challenges SET state=? WHERE id=?',(canonical(s),row['id']))
                    except Exception:pass
        finally:self.mutex.release()

    def view(self,cid=None):
        with self.brain.db() as db:
            challenges=[]
            for row in db.execute('SELECT * FROM prediction_challenges WHERE (? IS NULL OR id=?) ORDER BY rowid DESC LIMIT 20',(cid,cid)):
                s=json.loads(row['state']);c=json.loads(row['config']);rows=self._rows(db,row['id'])
                account_row=db.execute('SELECT state FROM event_lab_sessions WHERE id=?',(s['session_id'],)).fetchone() if s.get('session_id') else None
                account=json.loads(account_row[0]) if account_row else None
                challenges.append({**s,'id':row['id'],'config':c,'statistics':self.stats(rows,c['capital']),'account':account,'rounds':rows if cid else []})
        if cid and not challenges:raise ValueError('预测挑战不存在')
        return dict(challenges=challenges,error=self.error,execution_enabled=False,environment='reference_paper',
            notification_verified=False,notice='自动逐轮参考模拟；有效SKIP也可完成轮次，失败尝试不计目标，官方结果未到达时等待')

    def start(self):
        def run():
            while not self.stop.wait(1):self.tick()
        self.thread=threading.Thread(target=run,name='smart-money-prediction-challenge',daemon=True);self.thread.start()

    def close(self):
        self.stop.set();self.discovery.close()
        if getattr(self,'thread',None):self.thread.join(timeout=.2)
