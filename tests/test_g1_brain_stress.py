"""G1 scheduling and real Brain transactions share an isolated database."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import pytest
from ai.brain import Brain
from ai.worker_policy import BrainBusy
from test_prediction_challenge import system,one


@pytest.mark.parametrize('iteration',range(3))
def test_g1_brain_shared_database_stress(tmp_path,iteration):
    m,lab,cid,clock,provider,config=system(tmp_path,rounds=20)
    brain=lab.brain
    reflection=Brain(brain.path,clock=lambda:1000.);reflection.setup();reflection.recover()
    with reflection.db(True) as db:
        for i in range(12):
            db.execute("INSERT INTO brain_reflections(id,scope,data,status,attempts,next_try,error,lease_token) VALUES(?,?,'{}','PENDING',0,0,'','')",(f'stress-{i}','stress-reflections'))
    calls=[];call_lock=threading.Lock()
    class Provider:
        c=dict(timeout=5,interval=0,calls=100,model='ModelMock')
        def chat(self,*_):
            with reflection.db() as db:
                active=db.execute("SELECT id,lease_token FROM brain_reflections WHERE status='RUNNING'").fetchall()
            assert len(active)==1
            with call_lock:calls.append(tuple(active[0]))
            return json.dumps(dict(observation='fixture',hypothesis='unverified',invalidation='fixture'))
    barrier=threading.Barrier(6)
    def reflect():
        barrier.wait();deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                reflection.reflection_tick(Provider,threading.Event())
                with reflection.db() as db:
                    if db.execute("SELECT COUNT(*) FROM brain_reflections WHERE id LIKE 'stress-%' AND status='COMPLETED'").fetchone()[0]==12:return
            except BrainBusy:pass
            time.sleep(.005)
        raise AssertionError('reflection workers did not drain all tasks')
    def memory(writer):
        barrier.wait()
        for i in range(50):
            for attempt in range(50):
                try:
                    # Same source replays must resolve to one memory identity.
                    brain.put('stress',f'{writer}:{i}','observation',{'fixture':i},clock[0])
                    brain.put('stress',f'{writer}:{i}','observation',{'fixture':i},clock[0])
                    break
                except BrainBusy:
                    time.sleep(.005)
            else:raise AssertionError('memory lock retries exhausted')
    def g1():
        barrier.wait()
        for _ in range(20):
            for attempt in range(50):
                try:one(m,lab,cid,clock);break
                except BrainBusy:time.sleep(.005)
            else:raise AssertionError('G1 lock retries exhausted')
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(memory,i) for i in range(3)]+[pool.submit(g1)]+[pool.submit(reflect) for _ in range(2)]
        for future in futures:future.result(timeout=90)
    # Drain any lock-delayed scheduling without inventing additional identities.
    for _ in range(100):
        final=m.view(cid)['challenges'][0]
        if final['status']=='COMPLETED':break
        one(m,lab,cid,clock)
    final=m.view(cid)['challenges'][0]
    assert final['status']=='COMPLETED'
    assert final['statistics']['valid_completed']==20
    assert len(final['rounds'])==20
    assert lab.reconcile(final['session_id'])['verified']
    recovered=Brain(brain.path,clock=lambda:clock[0]);recovered.setup();recovered.recover()
    with recovered.db() as db:
        assert db.execute("SELECT COUNT(*) FROM brain_memories WHERE scope='stress'").fetchone()[0]==150
        assert db.execute("SELECT COUNT(*) FROM brain_reflections WHERE id LIKE 'stress-%' AND status='COMPLETED' AND attempts=1").fetchone()[0]==12
        assert db.execute("SELECT COUNT(*) FROM brain_memories WHERE scope='stress-reflections'").fetchone()[0]==12
        assert len(calls)==12 and len({row[0] for row in calls})==12 and len({row[1] for row in calls})==12
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
