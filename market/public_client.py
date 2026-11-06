"""Single public transport cache, exclusively leased by the market worker.

No credentials, ledger or account methods. Close never waits on network I/O;
the active fetch disposes its own transport on return after shutdown.
"""
from threading import Lock
from time import monotonic


class PublicClientCache:
    def __init__(self, clock=monotonic, ttl=600):
        self.clock, self.ttl = clock, ttl
        self.lock = Lock()
        self.closed = self.active = False
        self.venue = self.key = None
        self.created = 0

    @staticmethod
    def dispose(venue):
        if venue is not None:
            try:
                venue.client.session.close()
            except Exception:
                pass  # Cleanup must not leak URLs or mask the original failure.

    def fetch(self, factory, exchange, product, symbols, required, cancel, deadline):
        key = (exchange, product)
        with self.lock:
            if self.closed or self.active:
                raise ValueError("公开行情连接已关闭或正在使用")
            self.active = True
        failed = True
        try:
            self.check(cancel, deadline)
            if self.key != key or self.clock() - self.created >= self.ttl:
                old, self.venue = self.venue, None
                self.key = None
                self.dispose(old)
            if self.venue is None:
                self.venue = factory(exchange, product, "public")
                self.key, self.created = key, self.clock()
            self.check(cancel, deadline)
            result = self.venue.bars(symbols, required=required, cancel=cancel, deadline=deadline)
            self.check(cancel, deadline)
            failed = False
            return result
        finally:
            with self.lock:
                discard = failed or self.closed or cancel.is_set()
                old = self.venue if discard else None
                if discard:
                    self.venue = self.key = None
                self.active = False
            self.dispose(old)

    @staticmethod
    def check(cancel, deadline):
        if cancel.is_set() or monotonic() >= deadline:
            raise ValueError("行情任务已取消或超时")

    def close(self):
        with self.lock:
            self.closed = True
            old = None
            if not self.active:
                old, self.venue = self.venue, None
                self.key = None
        self.dispose(old)
