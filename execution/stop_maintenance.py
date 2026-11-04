"""Independent, bounded demo protection maintenance; never creates/cancels orders."""
import threading
import time


class StopMaintenance:
    def __init__(self, service, clock=time.time):
        self.service, self.clock = service, clock
        self.mutex = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.last_error = None

    def once(self, limit=4):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("每轮保护查询数量必须为 1 至 20")
        if not self.mutex.acquire(blocking=False):
            return []
        results = []
        try:
            for order in self.service.ledger.due(self.clock(), limit):
                if self.stop_event.is_set():
                    break
                cid = order["client_id"]
                failed = False
                try:
                    if order["stage"] == "TRIGGERED":
                        result = self.service.settle(cid)
                        if isinstance(result, dict) and result.get("complete") is True:
                            self.service.finalize(cid)
                    else:
                        current = self.service.reconcile(cid)
                        if current["stage"] == "TRIGGERED":
                            result = self.service.settle(cid)
                            if isinstance(result, dict) and result.get("complete") is True:
                                self.service.finalize(cid)
                except Exception:
                    failed = True
                self.service.ledger.maintenance_result(cid, self.clock(), failed)
                results.append(dict(client_id=cid, checked=not failed))
        finally:
            self.mutex.release()
        return results

    def start(self):
        with self.mutex:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            def loop():
                while not self.stop_event.is_set():
                    try:
                        self.once()
                        self.last_error = None
                    except Exception:
                        # Persistence failures do not terminate the recovery lane.
                        # No raw response/credentials go to logs or other lanes.
                        self.last_error = "保护维护记录失败，请检查数据库与磁盘；不得视为已核对"
                    self.stop_event.wait(.5)
            self.thread = threading.Thread(target=loop, name="demo-hosted-maintenance", daemon=True)
            self.thread.start()

    def stop(self, timeout=1):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout)
            return not self.thread.is_alive()
        return True
