"""Single flight inference. The model thread never sees a database or executor."""
from dataclasses import dataclass, field
from threading import Event, Thread
from time import monotonic, time


@dataclass
class Flight:
    stamp: dict
    deadline: float
    done: Event = field(default_factory=Event)
    cancel: Event = field(default_factory=Event)
    result: object = None
    error: str = ""


class Inference:
    """Only the trading scheduler (under Runtime.lock) changes the active flight."""
    def __init__(self):
        self.flight = None

    def start(self, stamp, provider, metrics, holdings, timeout):
        if self.flight is not None:
            return False
        flight = Flight(stamp=stamp, deadline=monotonic() + timeout)
        self.flight = flight
        provider.deadline = flight.deadline
        provider.cancel = flight.cancel

        def run():
            try:
                flight.result = provider.propose(metrics, holdings)
                flight.stamp["memory_refs"] = getattr(provider,"memory_refs",[])
            except Exception as err:
                # Provider supplies a sanitized error. Never log HTTP headers/body.
                flight.error = str(err) if type(err) is ValueError else "模型请求失败"
            finally:
                flight.done.set()

        Thread(target=run, name="smart-money-inference", daemon=True).start()
        return True

    def invalidate(self):
        if self.flight:
            self.flight.cancel.set()

    def ready(self):
        f = self.flight
        return bool(f and (f.done.is_set() or
                    (not f.cancel.is_set() and monotonic() >= f.deadline)))

    def poll(self):
        f = self.flight
        if not f:
            return None
        if f.cancel.is_set():
            if f.done.is_set():
                self.flight = None
            return None
        if monotonic() >= f.deadline or time() >= f.stamp["expires_at"]:
            f.cancel.set()
            if f.done.is_set():
                self.flight = None
            return ("TIMEOUT", f.stamp, "AI 超时，迟到结果已作废")
        if not f.done.is_set():
            return None
        self.flight = None
        if f.error:
            return ("ERROR", f.stamp, f.error)
        return ("READY", f.stamp, f.result)

