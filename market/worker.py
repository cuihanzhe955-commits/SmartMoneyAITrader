"""Bounded single-flight market I/O primitive; not yet wired into Runtime.

Cancellation is cooperative: an outstanding network call retains the only slot
until it actually returns. No executor, account, or database is passed here.
"""
from copy import deepcopy
from dataclasses import dataclass,field
import math
from threading import Event,Lock,Thread
from time import monotonic


@dataclass
class Request:
    scope: tuple
    deadline: float
    cancel: Event=field(default_factory=Event)
    done: Event=field(default_factory=Event)
    value: object=None
    failed: bool=False
    reported: bool=False


class MarketWorker:
    def __init__(self,clock=monotonic):
        self.clock=clock
        self.lock=Lock()
        self.flight=None
        self.closed=False

    def submit(self,scope,fetch,timeout):
        if (not isinstance(scope,tuple) or not scope or
            any(type(v) not in (str,int) for v in scope)):
            raise ValueError("行情任务必须使用不可变的平台/会话版本标识")
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
            raise ValueError("行情任务超时必须为有限正数")
        with self.lock:
            self._reap()
            if self.closed or self.flight is not None:return False
            task=Request(scope,self.clock()+timeout);self.flight=task
            def run():
                try:
                    if not task.cancel.is_set():
                        task.value=deepcopy(fetch(task.cancel,task.deadline))
                except Exception:
                    task.failed=True  # Never retain/log raw URLs, headers or keys.
                finally:task.done.set()
            try:
                Thread(target=run,name="smart-money-market-fetch",daemon=True).start()
            except Exception:
                task.failed=True
                task.done.set()
            return True

    def _reap(self):
        if self.flight and self.flight.reported and self.flight.done.is_set():
            self.flight=None

    def poll(self,expected_scope):
        with self.lock:
            task=self.flight
            if task is None:return None
            if task.reported:
                self._reap();return None
            if self.closed or task.cancel.is_set():return None
            status=None
            if task.scope!=expected_scope:status="STALE"
            elif self.clock()>=task.deadline:status="TIMEOUT"
            elif task.done.is_set():status="ERROR" if task.failed else "READY"
            if status is None:return None
            task.reported=True
            if status!="READY":task.cancel.set()
            value=task.value if status=="READY" else None
            result=dict(status=status,scope=task.scope,value=value)
            self._reap()
            return result

    def invalidate(self):
        with self.lock:
            if self.flight:
                self.flight.cancel.set();self.flight.reported=True
            self._reap()

    def close(self):
        with self.lock:
            self.closed=True
            if self.flight:
                self.flight.cancel.set();self.flight.reported=True
            self._reap()
