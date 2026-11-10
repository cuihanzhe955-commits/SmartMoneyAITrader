import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
from events.notification_outbox import NotificationIntent, NotificationOutbox


def intent(**changes):
    values=dict(event_id="fixture-event-1",session_id="fixture-session-1",provider="polymarket",
        product="event",environment="reference_paper",event_type="settlement",channel="feishu",
        account="synthetic-account",target="synthetic-target",message="合成通知；仅待发送记录")
    return NotificationIntent(**dict(values,**changes))


def test_pending_read_does_not_create_database(tmp_path):
    box=NotificationOutbox(tmp_path/'terminal.db')
    assert box.pending()==[] and not box.path.exists()


def test_durable_retry_is_deduplicated_without_claiming_delivery(tmp_path):
    box=NotificationOutbox(tmp_path/'terminal.db',clock=lambda:123.)
    first=box.enqueue(intent())
    restored=NotificationOutbox(box.path)
    assert restored.enqueue(intent())==dict(first,duplicate=True)
    rows=restored.pending()
    assert len(rows)==1 and rows[0]['created_at']==123.
    assert rows[0]['event']['message']==intent().message
    assert rows[0]['state']=='PENDING' and not rows[0]['delivery_verified']


def test_conflicting_retry_preserves_original_message(tmp_path):
    box=NotificationOutbox(tmp_path/'terminal.db');box.enqueue(intent())
    with pytest.raises(ValueError,match='未覆盖'):box.enqueue(intent(message='different'))
    assert box.pending()[0]['event']['message']==intent().message


@pytest.mark.parametrize('change',[dict(session_id='other'),dict(provider='okx'),dict(environment='paper'),
    dict(channel='telegram'),dict(account='other'),dict(target='other'),dict(event_id='other'),dict(product='spot')])
def test_different_scopes_and_destinations_are_not_accidentally_deduplicated(tmp_path,change):
    box=NotificationOutbox(tmp_path/'terminal.db');a=box.enqueue(intent());b=box.enqueue(intent(**change))
    assert a['id']!=b['id'] and len(box.pending())==2


def test_concurrent_duplicates_create_one_intent(tmp_path):
    box=NotificationOutbox(tmp_path/'terminal.db')
    with ThreadPoolExecutor(max_workers=2) as workers:
        results=list(workers.map(lambda _:box.enqueue(intent()),range(2)))
    assert sorted(r['duplicate'] for r in results)==[False,True]
    assert len(box.pending())==1


def test_busy_database_is_not_reported_as_enqueued_and_can_retry(tmp_path):
    box=NotificationOutbox(tmp_path/'terminal.db')
    with sqlite3.connect(box.path) as locked:
        locked.execute('CREATE TABLE existing(data TEXT)');locked.execute("INSERT INTO existing VALUES('keep')");locked.commit()
        locked.execute('BEGIN IMMEDIATE')
        with pytest.raises(ValueError,match='未确认入队'):box.enqueue(intent())
        locked.rollback()
    assert box.pending()==[]
    assert not box.enqueue(intent())['duplicate']
    with sqlite3.connect(box.path) as db:assert db.execute('SELECT * FROM existing').fetchall()==[('keep',)]


@pytest.mark.parametrize('change',[dict(api_key='not-accepted'),dict(state='SENT'),dict(message=''),dict(message='x'*4001),dict(channel='unknown')])
def test_invalid_or_delivery_claim_fields_are_rejected(change):
    with pytest.raises(ValidationError):intent(**change)


@pytest.mark.parametrize('limit',[0,101,True])
def test_read_limit_is_bounded(tmp_path,limit):
    with pytest.raises(ValueError):NotificationOutbox(tmp_path/'terminal.db').pending(limit)
