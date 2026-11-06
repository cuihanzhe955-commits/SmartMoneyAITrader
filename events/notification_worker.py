"""One bounded sender flight per worker, outside Runtime and database locks."""
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
        self.stop=threading.Event();self.lock=threading.Lock();self.flight=None;self.error='';self.thread=None

    def step(self):
        if not self.lock.acquire(False):return
        try:
            if self.stop.is_set():return
            f=self.flight
            if f:
                if not f.retired and (f.done.is_set() or self.outbox.clock()>=f.deadline):
                    outcome=f.outcome if f.done.is_set() and self.outbox.clock()<f.deadline else 'UNKNOWN'
                    receipt=f.result.receipt if outcome=='ACKNOWLEDGED' else ''
                    self.outbox.finish(f.item['id'],f.item['token'],outcome,receipt)
                    f.retired=True
                if f.done.is_set() and f.retired:self.flight=None
                else:return  # Quarantine a stuck sender; never spawn unbounded threads.
            item=self.outbox.claim(uuid4().hex,self.timeout,self.max_attempts)
            if not item:return
            f=Flight(item,item['lease_until']);self.flight=f
            def run():
                try:
                    result=self.sender(item['event'],item['id'])
                    if isinstance(result,SendAcknowledgement) and isinstance(result.receipt,str) and 0<len(result.receipt)<=128:
                        f.result=result;f.outcome='ACKNOWLEDGED'
                except RetryableSendError:f.outcome='RETRY'
                except RejectedSendError:f.outcome='FAILED'
                except Exception:f.outcome='UNKNOWN'  # No raw exception/body/key in persistence or diagnostics.
                finally:f.done.set()
            threading.Thread(target=run,name='smart-money-notification-send',daemon=True).start()
            self.error=''
        except Exception:self.error='通知工作器暂不可用；消息保留，交易与保护不受影响'
        finally:self.lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():return
        if self.stop.is_set():raise ValueError('通知工作器已关闭，请创建新实例')
        def run():
            while not self.stop.wait(.1):self.step()
        self.thread=threading.Thread(target=run,name='smart-money-notification-worker',daemon=True);self.thread.start()

    def close(self):
        self.stop.set()
        with self.lock:
            f=self.flight
            if f and not f.retired:
                try:self.outbox.finish(f.item['id'],f.item['token'],'UNKNOWN');f.retired=True
                except Exception:self.error='退出时通知结果未确认；重启按未知结果处理'
        if self.thread:self.thread.join(timeout=.2)
