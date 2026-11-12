"""Real spawn-process lease ownership tests, isolated SQLite and controlled clock."""
import json
import multiprocessing as mp
import threading
from pathlib import Path
import sqlite3
import pytest
from ai.brain import Brain

RESULT=dict(observation='synthetic',hypothesis='unverified',invalidation='fixture')


def seed(path):
    b=Brain(path,clock=lambda:1000.);b.setup()
    with b.db(True) as db:
        db.execute("INSERT INTO brain_reflections(id,scope,data,status,attempts,next_try,error,lease_token) VALUES('job','spot:fixture','{}','PENDING',0,0,'','')")


def child(path,clock,pipe,block):
    b=Brain(Path(path),clock=lambda:clock.value);b.setup();b.recover()
    class Provider:
        c=dict(timeout=5,interval=0,calls=100,model='ModelMock')
        def chat(self,*_):
            with b.db() as db:
                row=dict(db.execute("SELECT * FROM brain_reflections WHERE id='job'").fetchone())
            pipe.send(('claimed',row['lease_token'],row['lease_until']))
            if block:pipe.recv()
            return json.dumps(RESULT)
    try:
        while True:
            command=pipe.recv()
            if command=='exit':break
            b.reflection_tick(Provider,threading.Event())
            with b.db() as db:
                pipe.send(('state',dict(db.execute("SELECT * FROM brain_reflections WHERE id='job'").fetchone()),db.execute('SELECT COUNT(*) FROM brain_memories').fetchone()[0]))
    finally:pipe.close()


def receive(pipe):
    assert pipe.poll(15),'spawn process IPC timeout'
    return pipe.recv()


def test_spawn_kill_expiry_stale_reply_and_restart(tmp_path):
    ctx=mp.get_context('spawn');clock=ctx.Value('d',1000.);path=tmp_path/'lease.db';seed(path)
    pa,ca=ctx.Pipe();pb,cb=ctx.Pipe()
    a=ctx.Process(target=child,args=(str(path),clock,ca,True));b=ctx.Process(target=child,args=(str(path),clock,cb,False))
    a.start();b.start();ca.close();cb.close()
    try:
        pa.send('tick');claimed=receive(pa);assert claimed[0]=='claimed' and claimed[1]
        pb.send('tick');state=receive(pb);assert state[0]=='state' and state[1]['lease_token']==claimed[1] and state[2]==0
        a.terminate();a.join(10);assert not a.is_alive()
        clock.value=claimed[2]-.1;pb.send('tick');state=receive(pb);assert state[1]['status']=='RUNNING' and state[1]['attempts']==1
        clock.value=claimed[2]+.1;pb.send('tick');replacement=receive(pb);assert replacement[0]=='claimed' and replacement[1]!=claimed[1]
        state=receive(pb);assert state[1]['status']=='COMPLETED' and state[1]['attempts']==2 and state[2]==1
        stale=Brain(path,clock=lambda:clock.value);stale.setup()
        assert not stale._commit_reflection_result('job',claimed[1],{},dict(RESULT,observation='late old result'),'OldMock')
        pb.send('exit');b.join(10);assert b.exitcode==0
        # Another independent process represents application restart.
        pc,cc=ctx.Pipe();c=ctx.Process(target=child,args=(str(path),clock,cc,False));c.start();cc.close()
        try:
            pc.send('tick');state=receive(pc);assert state[0]=='state' and state[1]['status']=='COMPLETED' and state[2]==1
            pc.send('exit');c.join(10);assert c.exitcode==0
        finally:
            if c.is_alive():c.terminate();c.join(10)
            pc.close()
        with stale.db() as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert json.loads(db.execute('SELECT data FROM brain_memories').fetchone()[0])['model']=='ModelMock'
    finally:
        for p in (a,b):
            if p.is_alive():p.terminate()
            p.join(10)
        pa.close();pb.close()


def test_result_and_completed_are_one_transaction(tmp_path):
    path=tmp_path/'atomic.db';seed(path);b=Brain(path,clock=lambda:1000.);b.setup()
    with b.db(True) as db:
        db.execute("UPDATE brain_reflections SET status='RUNNING',lease_token='owner',lease_until=1100")
        db.execute("CREATE TRIGGER inject_failure BEFORE UPDATE OF status ON brain_reflections WHEN NEW.status='COMPLETED' BEGIN SELECT RAISE(ABORT,'synthetic mid transaction'); END")
    with pytest.raises(ValueError):b._commit_reflection_result('job','owner',{},RESULT,'ModelMock')
    with b.db() as db:
        assert db.execute('SELECT COUNT(*) FROM brain_memories').fetchone()[0]==0
        assert db.execute('SELECT status FROM brain_reflections').fetchone()[0]=='RUNNING'
    with b.db(True) as db:db.execute('DROP TRIGGER inject_failure')
    assert b._commit_reflection_result('job','owner',{},RESULT,'ModelMock')
    with b.db() as db:
        assert db.execute('SELECT COUNT(*) FROM brain_memories').fetchone()[0]==1
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_failed_legacy_migration_rolls_back_schema_and_rows(tmp_path):
    path=tmp_path/'legacy.db'
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE brain_reflections(id TEXT PRIMARY KEY,scope TEXT,data TEXT,status TEXT,attempts INTEGER,next_try REAL,error TEXT)")
        db.execute("INSERT INTO brain_reflections VALUES('legacy','fixture','{}','RUNNING',1,1100,'retained')")
        db.execute("CREATE TRIGGER migration_fault BEFORE UPDATE ON brain_reflections BEGIN SELECT RAISE(ABORT,'synthetic upgrade failure'); END")
        original=db.execute('SELECT * FROM brain_reflections').fetchall()
        original_schema=db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
    b=Brain(path,clock=lambda:1000.)
    with pytest.raises(ValueError):b.setup()
    assert not b.ready
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM brain_reflections').fetchall()==original
        assert db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()==original_schema
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        db.execute('DROP TRIGGER migration_fault')
    b.setup()
    with b.db() as db:
        row=db.execute("SELECT * FROM brain_reflections WHERE id='legacy'").fetchone()
        assert row['status']=='RUNNING' and row['lease_until']==1100 and row['error']=='retained'
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
