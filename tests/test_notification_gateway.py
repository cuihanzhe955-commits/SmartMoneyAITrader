import pytest

from events.notification_gateway import GatewayNotificationSender, GatewayOutcomeUnknown
from events.notification_outbox import NotificationOutbox
from events.notification_worker import NotificationWorker, RetryableSendError, RejectedSendError
from test_notification_outbox import intent


KEY = 'a' * 64


def response(request):
    return {'type': 'res', 'id': request['id'], 'ok': True, 'payload': {
        'runId': request['params']['idempotencyKey'],
        'channel': request['params']['channel'], 'messageId': 'synthetic-message-id',
    }}


@pytest.mark.parametrize('channel', ['feishu', 'telegram'])
def test_direct_send_protocol_and_stable_idempotency(channel):
    calls = []
    def rpc(request, *, timeout):
        calls.append(request)
        assert timeout == 8
        return response(request)
    sender = GatewayNotificationSender(rpc)
    event = intent(channel=channel).model_dump()
    assert sender(event, KEY).receipt == 'synthetic-message-id'
    sender(event, KEY)
    assert calls[0]['method'] == 'send'
    assert calls[0]['type'] == 'req'
    assert calls[0]['id'] != calls[1]['id']
    assert calls[0]['params'] == calls[1]['params'] == {
        'channel': channel, 'accountId': event['account'], 'to': event['target'],
        'message': event['message'], 'idempotencyKey': KEY,
    }


@pytest.mark.parametrize('fault', ['missing', 'id', 'type', 'ok', 'error', 'payload',
                                    'runId', 'channel', 'messageId', 'blank', 'long', 'numeric'])
def test_bad_or_uncorrelated_receipt_never_counts_as_acknowledged(fault):
    def rpc(request, *, timeout):
        r = response(request)
        if fault == 'missing': return None
        if fault == 'id': r['id'] = 'unrelated'
        if fault == 'type': r['type'] = 'event'
        if fault == 'ok': r['ok'] = 1
        if fault == 'error': r['error'] = {'message': 'private remote content'}
        if fault == 'payload': r['payload'] = []
        if fault == 'runId': r['payload']['runId'] = 'other-event'
        if fault == 'channel': r['payload']['channel'] = 'other-channel'
        if fault == 'messageId': r['payload'].pop('messageId')
        if fault == 'blank': r['payload']['messageId'] = ' '
        if fault == 'long': r['payload']['messageId'] = 'x' * 129
        if fault == 'numeric': r['payload']['messageId'] = 123
        return r
    with pytest.raises(GatewayOutcomeUnknown):
        GatewayNotificationSender(rpc)(intent().model_dump(), KEY)


@pytest.mark.parametrize('failure', [TimeoutError, ConnectionError, RetryableSendError])
def test_transport_failure_is_sanitized_and_cannot_request_unsafe_retry(failure):
    def rpc(*args, **kwargs): raise failure('private token and response')
    with pytest.raises(GatewayOutcomeUnknown) as error:
        GatewayNotificationSender(rpc)(intent().model_dump(), KEY)
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('change,key', [({'channel': 'unsupported'}, KEY),
    ({'message': '  '}, KEY), ({'target': ' target '}, KEY), ({'account': ''}, KEY),
    ({'extra': 'not allowed'}, KEY), ({}, 'invalid-key')])
def test_invalid_local_request_is_rejected_before_transport(change, key):
    calls = []
    sender = GatewayNotificationSender(lambda *a, **k: calls.append(a))
    event = dict(intent().model_dump(), **change)
    with pytest.raises(RejectedSendError): sender(event, key)
    assert calls == []


@pytest.mark.parametrize('accepted', [True, False])
def test_adapter_to_worker_persists_ack_or_unknown_without_repeat(tmp_path, accepted):
    calls = []
    def rpc(request, *, timeout):
        calls.append(request)
        if accepted: return response(request)
        # Gateway errors can include partial delivery; retryable is not proof of nonacceptance.
        return {'type': 'res', 'id': request['id'], 'ok': False,
                'error': {'code': 'UNAVAILABLE', 'retryable': True, 'message': 'private content'}}
    box = NotificationOutbox(tmp_path / 'isolated.db')
    key = box.enqueue(intent())['id']
    worker = NotificationWorker(box, GatewayNotificationSender(rpc))
    worker.step()
    assert worker.flight.done.wait(2)
    worker.step()
    worker.close()
    state = box.status(key)
    assert state['state'] == ('ACKNOWLEDGED' if accepted else 'UNKNOWN')
    assert not state['delivery_verified'] and 'private' not in str(state)
    restored = NotificationWorker(NotificationOutbox(box.path), GatewayNotificationSender(rpc))
    restored.step(); restored.close()
    assert len(calls) == 1


@pytest.mark.parametrize('timeout', [0, True, float('nan'), float('inf'), 61])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError): GatewayNotificationSender(lambda *a, **k: None, timeout)


def test_noncallable_rpc_rejected():
    with pytest.raises(ValueError): GatewayNotificationSender(None)
