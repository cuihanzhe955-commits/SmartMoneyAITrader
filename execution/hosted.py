"""Durable hosted-stop lifecycle foundation. No network writes or live activation.

Use an independent SQLite connection to the existing ledger, never a second
trading balance. Callers must reconcile spawned orders through execution.live;
a triggered stop remains blocking until that integration is implemented.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager

from events.store import encode
from execution.identity import digest, scope, position_version
from execution.protection import positive
from execution.live import number

TERMINAL = ("CANCELED", "FAILED")


def valid_id(value):
    return isinstance(value, str) and bool(value.strip())


class HostedStops:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=5)
        self.lock = threading.RLock()
        self.db.execute("PRAGMA synchronous=FULL")
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS hosted_stops(
                client_id TEXT PRIMARY KEY, slot TEXT NOT NULL,
                stage TEXT NOT NULL, body TEXT NOT NULL)""")
            self.db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS hosted_stop_slot
                ON hosted_stops(slot) WHERE stage NOT IN ('CANCELED','FAILED')""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS hosted_stop_events(
                id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, stage TEXT NOT NULL,
                body TEXT NOT NULL)""")

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield

    def close(self):
        self.db.close()

    def get(self, client_id):
        with self.lock:
            row = self.db.execute("SELECT body FROM hosted_stops WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            raise ValueError("保护单本地意图不存在，禁止认领外部订单")
        return json.loads(row[0])

    def _save(self, order, stage):
        order["stage"] = stage
        body = encode(order)
        self.db.execute("UPDATE hosted_stops SET stage=?,body=? WHERE client_id=?",
                        (stage, body, order["client_id"]))
        self.db.execute("INSERT INTO hosted_stop_events(client_id,stage,body) VALUES(?,?,?)",
                        (order["client_id"], stage, body))

    def plan(self, state, symbol, stop_price):
        c = state["config"]
        if (c.get("exchange"), c.get("product"), c.get("execution")) != ("okx", "spot", "demo"):
            raise ValueError("托管保护生命周期仍在模拟环境验收，禁止启用真实资金")
        position = state["positions"].get(symbol, {})
        qty, price = positive(position.get("qty")), positive(stop_price)
        if not state.get("account_ref") or not position.get("opening_order") or qty is None or price is None:
            raise ValueError("缺少账户绑定、持仓归属或有效保护数量与价格")
        # One outstanding stop per account/environment/instrument, across sessions.
        slot = digest([c["exchange"], c["execution"], c["product"], state["account_ref"], symbol])
        client = "sp" + digest([scope(state), symbol, position["opening_order"], str(qty), str(price)])[:30]
        order = dict(client_id=client, slot=slot, scope=scope(state), symbol=symbol,
                     quantity=str(qty), stop_price=str(price), portfolio_version=position_version(state),
                     opening_order=position["opening_order"], stage="PLANNED", exchange_id=None,
                     children=[], exchange_time=0, last_observation=None, cancel_requested=False)
        with self.transaction():
            if self.db.execute("SELECT 1 FROM hosted_stops WHERE client_id=?", (client,)).fetchone():
                existing = self.get(client)
                if existing["stage"] in TERMINAL:
                    raise ValueError("相同保护意图已终结；替换代次尚未验收，禁止自动重建")
                return existing
            if self.db.execute("SELECT 1 FROM hosted_stops WHERE slot=? AND stage NOT IN ('CANCELED','FAILED')", (slot,)).fetchone():
                raise ValueError("原保护单尚未终结或触发成交待核对，禁止重复创建或替换")
            self.db.execute("INSERT INTO hosted_stops VALUES(?,?,?,?)", (client, slot, "PLANNED", encode(order)))
            self._save(order, "PLANNED")
        return order

    def begin_create(self, client_id, state):
        """Commit BEFORE any future transport call. Repeating never resends."""
        with self.transaction():
            order = self.get(client_id)
            if order["stage"] != "PLANNED":
                raise ValueError("保护单已尝试提交，必须按原标识查单，禁止重复发送")
            if (order["scope"] != scope(state) or order["portfolio_version"] != position_version(state)
                    or state["positions"].get(order["symbol"], {}).get("opening_order") != order["opening_order"]):
                raise ValueError("账户、环境或持仓已变化，请重新核对保护数量")
            self._save(order, "SENDING")
        return order

    def uncertain(self, client_id):
        with self.transaction():
            order = self.get(client_id)
            if order["stage"] in TERMINAL or order["stage"] == "PLANNED":
                raise ValueError("当前保护状态不能标记为提交未知")
            self._save(order, "UNKNOWN")

    def acknowledge(self, client_id, response, *, cancel=False):
        """Acknowledgements never prove live protection or final cancellation."""
        with self.transaction():
            order = self.get(client_id)
            expected = "CANCEL_PENDING" if cancel else "SENDING"
            if order["stage"] != expected:
                raise ValueError("保护单回执与当前操作状态不符，需重新查询")
            rows = response.get("data") if isinstance(response, dict) else None
            if not isinstance(response, dict) or response.get("code") != "0" or not isinstance(rows, list) or len(rows) != 1:
                raise ValueError("保护单请求回执不可核验，需按原标识查单")
            row = rows[0]
            if (not isinstance(row, dict) or row.get("sCode") != "0" or not valid_id(row.get("algoId"))
                    or (row.get("algoClOrdId") and row["algoClOrdId"] != client_id)
                    or (order["exchange_id"] and row["algoId"] != order["exchange_id"])):
                raise ValueError("保护单请求未确认或标识不一致，需按原标识查单")
            order["exchange_id"] = row["algoId"]
            self._save(order, "CANCEL_PENDING" if cancel else "ACCEPTED")
        return order

    def observe(self, client_id, row):
        """Validate a single queried OKX detail, not absence from a pending list."""
        with self.transaction():
            order = self.get(client_id)
            if order["stage"] == "PLANNED":
                raise ValueError("保护单尚未发送，禁止认领外部订单")
            expected = dict(algoClOrdId=client_id, instId=order["symbol"] + "-USDT",
                            instType="SPOT", tdMode="cash", side="sell", ordType="conditional",
                            slOrdPx="-1", slTriggerPxType="last")
            if (not isinstance(row, dict) or any(row.get(k) != v for k, v in expected.items()) or not valid_id(row.get("algoId"))
                    or (order["exchange_id"] and order["exchange_id"] != row["algoId"])
                    or positive(row.get("sz")) != positive(order["quantity"])
                    or positive(row.get("slTriggerPx")) != positive(order["stop_price"])
                    or row.get("tpTriggerPx") not in (None, "")
                    or row.get("tgtCcy") not in (None, "", "base_ccy")):
                raise ValueError("保护单归属、现货类型、数量或止损参数不一致")
            stamp = str(row.get("uTime", ""))
            if not stamp.isascii() or not stamp.isdigit() or int(stamp) <= 0:
                raise ValueError("保护单更新时间不可核验")
            stamp = int(stamp)
            children = row.get("ordIdList", [])
            if (not isinstance(children, list) or any(not valid_id(v) for v in children)
                    or len(set(children)) != len(children)):
                raise ValueError("触发子订单清单无效")
            stages = dict(live="LIVE", effective="TRIGGERED", canceled="CANCELED", order_failed="FAILED")
            stage = stages.get(row.get("state"))
            if stage is None or (stage == "TRIGGERED" and not children) or (stage != "TRIGGERED" and children):
                raise ValueError("保护状态或触发订单无法核对，禁止释放持仓")
            if stage in TERMINAL and number(row.get("actualSz")) != 0:
                raise ValueError("终结保护单实际委托数量不为零或缺失，需核对子订单")
            observation = dict(state=stage, children=children, algo_id=row["algoId"])
            if stamp < order["exchange_time"] or (stamp == order["exchange_time"] and observation != order["last_observation"]):
                raise ValueError("保护单回报过期或同一版本冲突")
            previous = (order["last_observation"] or {}).get("state", order["stage"])
            if previous in TERMINAL + ("TRIGGERED",) and stage != previous:
                raise ValueError("保护单终态回退或触发结果冲突")
            if not set(order["children"]).issubset(children):
                raise ValueError("触发子订单清单回退")
            order.update(exchange_id=row["algoId"], children=children, exchange_time=stamp, last_observation=observation)
            if stage == "LIVE" and order["cancel_requested"]:
                stage = "CANCEL_PENDING"
            self._save(order, stage)
        return order

    def begin_cancel(self, client_id):
        with self.transaction():
            order = self.get(client_id)
            if order["stage"] == "PLANNED":
                self._save(order, "CANCELED")
            elif order["stage"] != "LIVE":
                raise ValueError("仅已核对的待触发保护单可请求撤销；未知状态先查单")
            else:
                order["cancel_requested"] = True
                self._save(order, "CANCEL_PENDING")
        return order

    def exit_blocked(self, client_id):
        # Triggered is NOT filled. Child fills/fees must still reach the ledger.
        return self.get(client_id)["stage"] not in TERMINAL
