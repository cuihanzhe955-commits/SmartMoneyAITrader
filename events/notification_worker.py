"""One bounded sender flight per channel, outside Runtime and database locks."""
from dataclasses import dataclass,field
import math
import threading
from uuid import uuid4


class RetryableSendError(Exception):
    """Adapter positively knows the remote service did NOT accept the request."""


class RejectedSendError(Exception):
    """Definitive rejection, not an uncertain network outcome."""


@dataclass(frozen=True)
class SendAcknowledgement:
    receipt: str


@dataclass
class Flight:
    item: dict
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    outcome: str = 'UNKNOWN'
    retired: bool = False


class NotificationWorker:
    def __init__(self,outbox,sender,timeout=10.,max_attempts=3):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=60:
            raise ValueError('通知超时应大于0且不超过60秒')
        if type(max_attempts) is not int or not 1<=max_attempts<=10:raise ValueError('通知最多尝试次数应为1至10')
        self.outbox,self.sender,self.timeout,self.max_attempts=outbox,sender,timeout,max_attempts
        self.stop=threading.Event();self.lock=threading.Lock();self.flights={};self.error='';self.thread=None

    @property
    def flight(self):
        """First outstanding attempt (compatibility for single-channel callers)."""
        return next(iter(self.flights.values()), None)

    def _advance_channel(self, channel):
        flight = self.flights.get(channel)
        if flight:
            expired = self.outbox.clock() >= flight.deadline
            if not flight.retired and (expired or flight.done.is_set()):
                state = 'UNKNOWN' if expired else flight.outcome
                receipt = flight.result.receipt if state == 'ACKNOWLEDGED' else ''
                self.outbox.finish(flight.item['id'], flight.item['token'], state, receipt)
                flight.retired = True
            if not flight.retired or not flight.done.is_set():
                return
            del self.flights[channel]
        item = self.outbox.claim(uuid4().hex, self.timeout, self.max_attempts, channel)
        if item:
            flight = Flight(item, item['lease_until'])
            self.flights[channel] = flight
            threading.Thread(target=self._send, args=(flight,),
                             name='smart-money-send-' + channel, daemon=True).start()

    def _send(self, flight):
        try:
            result = self.sender(flight.item['event'], flight.item['id'])
            if (isinstance(result, SendAcknowledgement) and isinstance(result.receipt, str)
                    and 0 < len(result.receipt) <= 128):
                flight.result, flight.outcome = result, 'ACKNOWLEDGED'
        except RetryableSendError:
            flight.outcome = 'RETRY'
        except RejectedSendError:
            flight.outcome = 'FAILED'
        except Exception:
            flight.outcome = 'UNKNOWN'
        finally:
            flight.done.set()

    def step(self):
        if not self.lock.acquire(False):
            return
        try:
            if self.stop.is_set():
                return
            self.error = ''
            for channel in ('feishu', 'telegram'):
                try:
                    self._advance_channel(channel)
                except Exception:
                    self.error = '通知工作器暂不可用；消息保留，交易与保护不受影响'
        finally:
            self.lock.release()

    def start(self):
        def run():
            while not self.stop.wait(.1):self.step()
        with self.lock:
            if self.stop.is_set():
                raise ValueError('通知工作器已关闭，请创建新实例')
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=run, name='smart-money-notification-worker', daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        with self.lock:
            for f in self.flights.values():
                if f.retired:continue
                try:self.outbox.finish(f.item['id'],f.item['token'],'UNKNOWN');f.retired=True
                except Exception:self.error='退出时通知结果未确认；重启按未知结果处理'
        if self.thread:self.thread.join(timeout=.2)
