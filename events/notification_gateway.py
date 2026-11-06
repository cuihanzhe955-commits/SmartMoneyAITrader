"""OpenClaw direct-send protocol adapter; no connection or credential discovery.

rpc(frame, timeout=seconds) must use an authenticated Gateway connection and return
the response frame. Runtime wiring and the connection transport are separate work.
"""
import math
import re
from uuid import uuid4

from pydantic import ValidationError

from events.notification_outbox import NotificationIntent
from events.notification_worker import RejectedSendError, SendAcknowledgement


class GatewayOutcomeUnknown(Exception):
    """The send may have taken effect. Never automatically retry this outcome."""


class GatewayNotificationSender:
    def __init__(self, rpc, timeout=8.):
        if not callable(rpc):
            raise ValueError('Gateway请求器必须可调用')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError('Gateway请求超时应大于0且不超过60秒')
        self.rpc, self.timeout = rpc, timeout

    def __call__(self, event, key):
        try:
            intent = NotificationIntent.model_validate(event)
        except ValidationError:
            raise RejectedSendError('通知内容未通过本地校验，未发送') from None
        if (not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key)
                or not intent.message.strip()
                or any(value != value.strip() or not value.strip()
                       for value in (intent.account, intent.target))):
            raise RejectedSendError('通知标识、账号或目标无效，未发送')

        request = {
            'type': 'req', 'id': uuid4().hex, 'method': 'send',
            'params': {
                'to': intent.target, 'message': intent.message,
                'channel': intent.channel, 'accountId': intent.account,
                'idempotencyKey': key,
            },
        }
        request_id = request['id']
        try:
            response = self.rpc(request, timeout=self.timeout)
        except Exception:
            # Even a retryable server/transport error may follow a partial send.
            raise GatewayOutcomeUnknown('Gateway发送结果未确认，未自动重发') from None
        if (not isinstance(response, dict) or response.get('type') != 'res'
                or response.get('id') != request_id or response.get('ok') is not True
                or response.get('error') is not None):
            raise GatewayOutcomeUnknown('Gateway回执未确认，未自动重发')
        payload = response.get('payload')
        if (not isinstance(payload, dict) or payload.get('runId') != key
                or payload.get('channel') != intent.channel):
            raise GatewayOutcomeUnknown('Gateway回执与通知不匹配，未自动重发')
        receipt = payload.get('messageId')
        if not isinstance(receipt, str) or not receipt.strip() or len(receipt) > 128:
            raise GatewayOutcomeUnknown('Gateway未提供有效消息回执，未自动重发')
        return SendAcknowledgement(receipt)
