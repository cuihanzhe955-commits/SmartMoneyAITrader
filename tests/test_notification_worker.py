import threading,time
from concurrent.futures import ThreadPoolExecutor
import pytest
from events.notification_outbox import NotificationOutbox
from events.notification_worker import NotificationWorker,SendAcknowledgement,RetryableSendError,RejectedSendError
from test_notification_outbox import intent


def setup(tmp_path,sender,**kw):
    clock=[100.];box=NotificationOutbox(tmp_path/'terminal.db',clock=lambda:clock[0])
    key=box.enqueue(intent())['id'];worker=NotificationWorker(box,sender,timeout=2,**kw)
    return box,worker,key,clock


def finish(worker):
    assert worker.flight.done.wait(2)
    worker.step()


def test_acknowledgement_is_durable_but_is_not_delivery_verification(tmp_path):
    calls=[]
    def sender(event,key):calls.append(key);return SendAcknowledgement('synthetic-receipt')
    box,w,key,clock=setup(tmp_path,sender);w.step();finish(w)
    assert box.status(key)['state']=='ACKNOWLEDGED' and not box.status(key)['delivery_verified']
    assert box.enqueue(intent())['state']=='ACKNOWLEDGED'
    assert box.pending()==[]
    restored=NotificationWorker(NotificationOutbox(box.path),sender);restored.step()
    assert calls==[key]


def test_explicit_nonacceptance_uses_finite_backoff_without_new_ids(tmp_path):
    calls=[]
    def sender(event,key):calls.append(key);raise RetryableSendError('not stored')
    box,w,key,clock=setup(tmp_path,sender,max_attempts=2)
    w.step();finish(w)
    assert box.status(key)['state']=='RETRY' and box.status(key)['next_try']==105
    w.step();assert len(calls)==1
    clock[0]=105;w.step();finish(w)
    assert box.status(key)['state']=='FAILED' and calls==[key,key]
    clock[0]=10000;w.step();assert len(calls)==2


@pytest.mark.parametrize('behavior',['timeout','generic_error','invalid_ack','rejection'])
def test_ambiguous_outcomes_never_get_blind_retries(tmp_path,behavior):
    def sender(event,key):
        if behavior=='timeout':raise TimeoutError('private response must not persist')
        if behavior=='generic_error':raise RuntimeError('private response must not persist')
        if behavior=='rejection':raise RejectedSendError('private response must not persist')
        return {'ok':True}
    box,w,key,clock=setup(tmp_path,sender);w.step();finish(w)
    assert box.status(key)['state']==('FAILED' if behavior=='rejection' else 'UNKNOWN')
    assert 'private' not in box.status(key)['error']
    clock[0]+=1000;w.step();assert box.status(key)['attempts']==1


def test_hung_sender_is_quarantined_late_reply_ignored_and_close_is_bounded(tmp_path):
    started=threading.Event();release=threading.Event();calls=[]
    def sender(event,key):calls.append(key);started.set();release.wait(3);return SendAcknowledgement('late')
    box,w,key,clock=setup(tmp_path,sender);w.step();assert started.wait(1)
    box.enqueue(intent(event_id='second'));clock[0]+=3;w.step()
    assert box.status(key)['state']=='UNKNOWN'
    for _ in range(3):w.step()
    assert calls==[key]  # No unbounded sender threads for later rows.
    before=time.monotonic();w.close();assert time.monotonic()-before<.5
    release.set();assert w.flight.done.wait(2);w.step()
    assert box.status(key)['state']=='UNKNOWN'


def test_restart_recovery_and_attempt_token_fence(tmp_path):
    box=NotificationOutbox(tmp_path/'terminal.db',clock=lambda:100)
    key=box.enqueue(intent())['id'];assert box.claim('old-token',2,3)
    # A second process cannot claim a still-active attempt.
    assert box.claim('other-token',2,3) is None
    restored=NotificationOutbox(box.path,clock=lambda:103)
    assert restored.claim('new-token',2,3) is None
    assert restored.status(key)['state']=='UNKNOWN'
    assert not box.finish(key,'old-token','ACKNOWLEDGED','late')
    assert not box.finish(key,'invented-token','RETRY')


def test_two_workers_cannot_submit_the_same_intent(tmp_path):
    calls=[];guard=threading.Lock()
    def sender(event,key):
        with guard:calls.append(key)
        return SendAcknowledgement('accepted')
    box,a,key,clock=setup(tmp_path,sender);b=NotificationWorker(box,sender)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda w:w.step(),[a,b]))
    for w in (a,b):
        if w.flight:finish(w)
    assert calls==[key]


def test_daemon_worker_starts_and_stops_without_runtime_or_network(tmp_path):
    box,w,key,clock=setup(tmp_path,lambda *_:SendAcknowledgement('accepted'))
    w.start();w.start();deadline=time.monotonic()+2
    while time.monotonic()<deadline and box.status(key)['state']!='ACKNOWLEDGED':time.sleep(.02)
    w.close();assert box.status(key)['state']=='ACKNOWLEDGED'
    assert not w.thread.is_alive()


def test_legacy_pending_table_remains_readable_and_limits_apply_after_filter(tmp_path):
    box,w,key,clock=setup(tmp_path,lambda *_:SendAcknowledgement('accepted'))
    w.step();finish(w)
    second=box.enqueue(intent(event_id='second'))['id']
    assert [r['id'] for r in box.pending(limit=1)]==[second]


@pytest.mark.parametrize('config',[{'timeout':0},{'timeout':float('nan')},{'timeout':True},{'max_attempts':0},{'max_attempts':True}])
def test_invalid_resource_limits_are_rejected(tmp_path,config):
    with pytest.raises(ValueError):NotificationWorker(NotificationOutbox(tmp_path/'terminal.db'),lambda *_:None,**config)
