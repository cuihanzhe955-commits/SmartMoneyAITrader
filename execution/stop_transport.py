"""Explicit demo-only hosted stop service; not enabled in Runtime or the UI."""
import threading
import time
from contextlib import nullcontext

from execution.hosted import TERMINAL
from execution.identity import scope
from execution.live import number


class DemoStops:
    def __init__(self, ledger, venue, read_state, commit_lock=None):
        self.ledger, self.venue, self.read_state = ledger, venue, read_state
        self.lock = threading.Lock()
        self.commit_lock = commit_lock

    def guard(self, order):
        v, s = self.venue, self.read_state()
        if (v.name != "okx" or v.swap or v.env != "demo"
                or v.client.id != "okx" or v.client.options.get("sandboxMode") is not True
                or v.client.headers.get("x-simulated-trading") != "1"):
            raise ValueError("保护单写入仅限已核验的 OKX 模拟环境")
        if scope(s) != order["scope"] or s["config"].get("execution") != "demo":
            raise ValueError("保护单账户或执行环境已变化")
        uid = v.permission_check().get("venue_account_id")
        if not s.get("venue_account_id") or uid != s["venue_account_id"]:
            raise ValueError("保护单账户身份不符")
        return s

    def prepare(self, order, state):
        v, c = self.venue, self.venue.client
        if state.get("admitted") is not True:
            raise ValueError("模拟账户未通过启动核验")
        c.load_markets(True)
        market = c.market(v.pair(order["symbol"]))
        v.spot_rules(order["symbol"], market)
        qty, stop = number(order["quantity"]), number(order["stop_price"])
        if (qty <= 0 or stop <= 0
                or qty != number(c.amount_to_precision(market["symbol"], str(qty)))
                or stop != number(c.price_to_precision(market["symbol"], str(stop)))):
            raise ValueError("保护数量或止损价不符合精度，禁止静默缩减")
        for field, value in (("amount", qty), ("price", stop), ("cost", qty * stop)):
            bounds = market.get("limits", {}).get(field, {})
            if ((bounds.get("min") is not None and value < number(bounds["min"]))
                    or (bounds.get("max") is not None and value > number(bounds["max"]))):
                raise ValueError("保护单不符合交易所数量、价格或金额限额")
        if qty != number(state["positions"].get(order["symbol"], {}).get("qty")):
            raise ValueError("保护数量与当前持仓不一致")
        if v.audit_spot(state).get("dedicated_balance_match") is not True:
            raise ValueError("策略资金与账户余额未核对")
        if v.algo_inventory():
            raise ValueError("存在未核对保护单，禁止重复创建")
        bid, ask, stamp = v.quote(order["symbol"])
        if not 0 <= time.time() - stamp <= 10 or not 0 < stop < number(bid) <= number(ask):
            raise ValueError("保护行情过期或止损价已触发，应先核对退出方案")
        return dict(instId=market["id"], tdMode="cash", side="sell", ordType="conditional",
                    sz=str(qty), slTriggerPx=str(stop), slOrdPx="-1", slTriggerPxType="last",
                    algoClOrdId=order["client_id"], tgtCcy="base_ccy"), stamp

    def create(self, client_id):
        with self.lock:
            order = self.ledger.get(client_id)
            if order["stage"] != "PLANNED":
                raise ValueError("原保护单已尝试发送，必须先查单，禁止重复发送")
            params, stamp = self.prepare(order, self.guard(order))
            # A fresh binding/position check follows the network preflight.
            current = self.guard(order)
            if current.get("admitted") is not True or not 0 <= time.time() - stamp <= 10:
                raise ValueError("发送前授权或行情已失效")
            self.ledger.begin_create(client_id, current)
            try:
                result = self.venue.client.privatePostTradeOrderAlgo(params)
                return self.ledger.acknowledge(client_id, result)
            except Exception:
                self.ledger.uncertain(client_id)
                raise ValueError("保护单提交结果未确认，已保留原标识等待查询") from None

    def _query(self, client_id):
        order = self.ledger.get(client_id)
        self.guard(order)
        try:
            return self.ledger.observe(client_id, self.venue.lookup_stop(client_id))
        except Exception:
            if order["stage"] not in TERMINAL + ("PLANNED",):
                self.ledger.uncertain(client_id)
            raise ValueError("保护单查询未确认，禁止重发或释放持仓") from None

    def reconcile(self, client_id):
        with self.lock:
            return self._query(client_id)

    def settle(self, client_id):
        """Read spawned orders and fills; commit all receipts in one transaction."""
        with self.lock:
            order = self._query(client_id)
            if order["stage"] != "TRIGGERED":
                raise ValueError("保护单尚未确认触发")
            receipts = {}
            for exchange_id in order["children"]:
                report = self.venue.client.fetch_order(exchange_id, self.venue.pair(order["symbol"]))
                trades = self.venue.executions({"symbol": order["symbol"], "side": "SELL"}, report)
                receipts[exchange_id] = (report, trades)
            self.guard(order)
            with self.commit_lock if self.commit_lock is not None else nullcontext():
                return self.ledger.settle_children(client_id, receipts)

    def cancel(self, client_id):
        with self.lock:
            order = self._query(client_id)
            if order["stage"] in TERMINAL:
                return order
            # The ledger disallows repeat cancel writes and triggered-order cancels.
            self.guard(order)
            order = self.ledger.begin_cancel(client_id)
            try:
                response = self.venue.client.privatePostTradeCancelAlgos([
                    dict(algoId=order["exchange_id"], instId=order["symbol"] + "-USDT")])
                return self.ledger.acknowledge(client_id, response, cancel=True)
            except Exception:
                self.ledger.uncertain(client_id)
                raise ValueError("保护单撤销结果未确认，必须继续查原单") from None
