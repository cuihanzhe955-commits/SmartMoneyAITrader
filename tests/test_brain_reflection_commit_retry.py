"""Deterministic post-provider contention, using only disposable databases."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import pytest
from ai.brain import Brain, BrainSettings
from ai.worker_policy import BrainBusy
from test_brain_spawn_recovery import seed, RESULT


def fixture(tmp_path):
    path=tmp_path/'commit.db';seed(path)
    b=Brain(path,clock=lambda:1000.);b.setup();b.recover()
    busy=threading.Event();returned=threading.Event();release=threading.Event()
    calls=[];tokens=[]
    original=b._commit_reflection_result
    def commit(*args):
        tokens.append(args[1])
        try:return original(*args)
        except BrainBusy:busy.set();raise
    b._commit_reflection_result=commit
    class Provider:
        c=dict(timeout=5,interval=0,calls=100,model='ModelMock')
        def chat(self,*args):
            calls.append(1);returned.set()
            assert release.wait(5)
            return json.dumps(RESULT)
    return b,Provider,busy,returned,release,calls,tokens


def locked_result(b,provider,returned,release):
    pool=ThreadPoolExecutor(1)
    future=pool.submit(b.reflection_tick,provider,threading.Event())
    assert returned.wait(5)
    lock=sqlite3.connect(b.path);lock.execute('BEGIN IMMEDIATE')
    release.set()
    return pool,future,lock


def verify(b,calls):
    with b.db() as db:
        row=db.execute('SELECT * FROM brain_reflections').fetchone()
        assert row['status']=='COMPLETED' and row['attempts']==1
        assert db.execute('SELECT COUNT(*) FROM brain_memories').fetchone()[0]==1
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert len(calls)==1 and b._pending_reflection is None


def test_real_write_lock_recovers_same_result(tmp_path):
    b,p,busy,returned,release,calls,tokens=fixture(tmp_path)
    pool,future,lock=locked_result(b,p,returned,release)
    try:
        assert busy.wait(5)
        lock.rollback();lock.close();lock=None
        future.result(5)
    finally:
        if lock:lock.close()
        pool.shutdown()
    verify(b,calls);assert len(set(tokens))==1


@pytest.mark.parametrize('workers',[1,2])
def test_cached_result_cross_tick_and_competing_workers(tmp_path,workers):
    b,p,busy,returned,release,calls,tokens=fixture(tmp_path)
    b._commit_retry_seconds=0
    pool,future,lock=locked_result(b,p,returned,release)
    try:
        assert busy.wait(5)
        with pytest.raises(BrainBusy):future.result(5)
        assert b._pending_reflection is not None
    finally:lock.close();pool.shutdown()
    barrier=threading.Barrier(workers)
    def tick():barrier.wait();b.reflection_tick(p,threading.Event())
    with ThreadPoolExecutor(workers) as pool:list(pool.map(lambda _:tick(),range(workers)))
    verify(b,calls);assert len(set(tokens))==1


def test_cached_old_token_cannot_overwrite_new_owner(tmp_path):
    b,p,busy,returned,release,calls,tokens=fixture(tmp_path)
    b._commit_retry_seconds=0
    pool,future,lock=locked_result(b,p,returned,release)
    try:
        with pytest.raises(BrainBusy):future.result(5)
    finally:lock.close();pool.shutdown()
    old=b._pending_reflection['token']
    with b.db(True) as db:
        db.execute("UPDATE brain_reflections SET lease_token='replacement',attempts=2,lease_until=1100")
    b.reflection_tick(p,threading.Event())
    assert b._pending_reflection is None and len(calls)==1
    with b.db() as db:
        assert db.execute('SELECT lease_token FROM brain_reflections').fetchone()[0]=='replacement'
        assert db.execute('SELECT COUNT(*) FROM brain_memories').fetchone()[0]==0
    assert old!='replacement'


def test_stop_cancels_wait_and_releases_connections(tmp_path):
    b,p,busy,returned,release,calls,tokens=fixture(tmp_path)
    stop=threading.Event()
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(b.reflection_tick,p,stop)
        assert returned.wait(5)
        with closing(sqlite3.connect(b.path)) as lock:
            lock.execute('BEGIN IMMEDIATE');release.set()
            assert busy.wait(5);stop.set();future.result(2)
            lock.rollback()
    assert b._pending_reflection is not None
    with b.db(True) as db:db.execute('SELECT 1')
    b.reflection_tick(p,threading.Event());verify(b,calls)


def test_expired_cache_discarded(tmp_path):
    b,p,busy,returned,release,calls,tokens=fixture(tmp_path)
    b._commit_retry_seconds=0
    pool,future,lock=locked_result(b,p,returned,release)
    try:
        with pytest.raises(BrainBusy):future.result(5)
    finally:lock.close();pool.shutdown()
    b.clock=lambda:1035.
    b.settings(BrainSettings(auto_reflect=False))
    b.reflection_tick(p,threading.Event())
    assert b._pending_reflection is None and len(calls)==1
    with b.db() as db:assert db.execute('SELECT COUNT(*) FROM brain_memories').fetchone()[0]==0


def test_two_distinct_jobs_serialize_results_during_write_contention(tmp_path):
    """Two callers, two jobs, real locks: admission prevents concurrent valid results."""
    b,_,busy,_,_,_,_=fixture(tmp_path)
    with b.db(True) as db:
        db.execute("INSERT INTO brain_reflections(id,scope,data,status,attempts,next_try,error,lease_token) VALUES('job-2','spot:fixture','{}','PENDING',0,0,'','')")
    b._commit_retry_seconds=0
    entered=[threading.Event(),threading.Event()]
    releases=[threading.Event(),threading.Event()]
    calls=[];call_lock=threading.Lock()
    class Provider:
        c=dict(timeout=5,interval=0,calls=100,model='ModelMock')
        def chat(self,*args):
            with b.db() as db:
                active=db.execute("SELECT id,lease_token FROM brain_reflections WHERE status='RUNNING'").fetchall()
            assert len(active)==1
            with call_lock:
                index=len(calls);calls.append(tuple(active[0]))
            entered[index].set()
            assert releases[index].wait(5)
            return json.dumps(dict(RESULT,observation=active[0]['id']))
    with ThreadPoolExecutor(2) as pool:
        for index in range(2):
            busy.clear()
            future=pool.submit(b.reflection_tick,Provider,threading.Event())
            lock=None
            try:
                assert entered[index].wait(5)
                # While the provider runs, another tick cannot start a different job.
                pool.submit(b.reflection_tick,Provider,threading.Event()).result(5)
                assert len(calls)==index+1
                lock=sqlite3.connect(b.path);lock.execute('BEGIN IMMEDIATE')
                releases[index].set()
                assert busy.wait(5)
                with pytest.raises(BrainBusy):future.result(5)
                assert b._pending_reflection['job_id']==calls[index][0]
                # An occupied cache is retried, never overwritten by another provider.
                with pytest.raises(BrainBusy):
                    pool.submit(b.reflection_tick,Provider,threading.Event()).result(5)
                assert len(calls)==index+1
                assert b._pending_reflection['job_id']==calls[index][0]
            finally:
                releases[index].set()
                if lock:lock.close()
            pool.submit(b.reflection_tick,Provider,threading.Event()).result(5)
            assert b._pending_reflection is None
    with b.db() as db:
        jobs=db.execute('SELECT id,status,attempts FROM brain_reflections ORDER BY id').fetchall()
        assert [(r['id'],r['status'],r['attempts']) for r in jobs]==[
            ('job','COMPLETED',1),('job-2','COMPLETED',1)]
        memories=db.execute('SELECT data FROM brain_memories').fetchall()
        assert len(memories)==2
        assert {json.loads(r[0])['observation'] for r in memories}=={'job','job-2'}
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert len(calls)==2 and len({c[0] for c in calls})==2 and len({c[1] for c in calls})==2
