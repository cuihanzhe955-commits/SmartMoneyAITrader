"""Runtime recovery routes only to the original demo session/account."""
from execution.stop_transport import DemoStops


class RuntimeStops:
    def __init__(self, runtime, ledger):
        self.runtime, self.ledger = runtime, ledger

    def service(self, client_id):
        rt = self.runtime
        cid = self.ledger.get(client_id)["scope"][0]
        def read():
            with rt.lock:
                state = rt.db.load(cid)
                if not state or state["config"].get("execution") != "demo":
                    raise ValueError("保护恢复仅限原模拟会话")
                rt.check_binding(state)
                return state
        state = read()
        return DemoStops(self.ledger, rt.venue(state["config"]), read, rt.lock)

    def reconcile(self, client_id):
        return self.service(client_id).reconcile(client_id)

    def settle(self, client_id):
        return self.service(client_id).settle(client_id)
