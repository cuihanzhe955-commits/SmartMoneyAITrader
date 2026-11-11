import sqlite3,threading,time
import pytest
from ai.brain import Brain
from ai.worker_policy import BrainBusy,run_worker


def test_actual_busy_rolls_back_and_recovers(tmp_path):
    brain=Brain(tmp_path/'isolated.db');brain.setup()
    with sqlite3.connect(brain.path) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with pytest.raises(BrainBusy):
            with brain.db(True) as db:
                db.execute('INSERT INTO brain_cursors VALUES(?,?)',('unique',1))
        lock.rollback()
    for _ in range(2):
        with brain.db(True) as db:
            db.execute('INSERT OR IGNORE INTO brain_cursors VALUES(?,?)',('unique',1))
    with brain.db() as db:assert db.execute('SELECT COUNT(*) FROM brain_cursors').fetchone()[0]==1


def test_busy_backoff_is_interruptible():
    stop=threading.Event();calls=[];errors=[]
    def tick():
        calls.append(time.monotonic());raise BrainBusy('fixture')
    worker=threading.Thread(target=run_worker,args=(tick,stop,errors.append,.02));worker.start()
    time.sleep(.18);stop.set();worker.join(.2)
    assert not worker.is_alive() and 2<=len(calls)<=4
    assert errors and all('退避' in value for value in errors)


def test_unexpected_failure_is_logged_and_stops(caplog):
    stop=threading.Event();errors=[]
    def tick():raise RuntimeError('synthetic program fault')
    run_worker(tick,stop,errors.append,.001)
    assert 'synthetic program fault' in caplog.text and '已停止' in errors[0]


def test_partial_write_is_rolled_back(tmp_path):
    brain=Brain(tmp_path/'isolated.db');brain.setup()
    with pytest.raises(RuntimeError):
        with brain.db(True) as db:
            db.execute('INSERT INTO brain_cursors VALUES(?,?)',('uncommitted',1))
            raise RuntimeError('fixture')
    with brain.db() as db:assert db.execute('SELECT COUNT(*) FROM brain_cursors').fetchone()[0]==0


def test_concurrent_brain_writes_preserve_unique_records(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    brain=Brain(tmp_path/'concurrent.db');brain.setup()
    def write(index):
        for attempt in range(50):
            try:
                with brain.db(True) as db:
                    db.execute('INSERT OR IGNORE INTO brain_cursors VALUES(?,?)',(str(index),index))
                return
            except BrainBusy:
                time.sleep(min(.05,.005*(2**min(attempt,4))))
        raise AssertionError('bounded retries exhausted')
    with ThreadPoolExecutor(max_workers=4) as workers:list(workers.map(write,range(80)))
    recovered=Brain(brain.path);recovered.recover()
    with recovered.db() as db:
        assert db.execute('SELECT COUNT(*) FROM brain_cursors').fetchone()[0]==80
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_brain_worker_error_channels_do_not_overwrite_each_other(tmp_path):
    brain=Brain(tmp_path/'isolated.db')
    brain.setup()
    brain.sync_error='模拟事件同步暂不可用'
    brain.reflection_error='AI复盘数据库暂忙'
    brain.runtime_error='Runtime恢复暂不可用'
    brain.event_error='EventLab学习暂不可用'
    brain.error='兼容旧调用的外部错误'
    combined=brain.error
    for message in ('模拟事件同步暂不可用','AI复盘数据库暂忙','Runtime恢复暂不可用',
                    'EventLab学习暂不可用','兼容旧调用的外部错误'):
        assert message in combined
    brain.sync_error=''
    assert 'AI复盘数据库暂忙' in brain.error
    assert 'Runtime恢复暂不可用' in brain.error
    assert 'EventLab学习暂不可用' in brain.error
    assert '兼容旧调用的外部错误' in brain.error
    assert '模拟事件同步暂不可用' not in brain.error
