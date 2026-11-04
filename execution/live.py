"""Durable IOC intents and incremental, idempotent spot fill accounting."""
import json
import math
from decimal import Decimal

from events.store import encode
from execution.identity import decision_tag, position_version

FINAL = ("FILLED", "PARTIAL_CANCELLED", "CANCELLED", "REJECTED")
OPEN = "stage NOT IN ('FILLED','PARTIAL_CANCELLED','CANCELLED','REJECTED')"


def hosted_pending(db):
    if not db.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_stops'").fetchone():
        return False
    return bool(db.db.execute("SELECT 1 FROM hosted_stops WHERE stage NOT IN ('CANCELED','FAILED') LIMIT 1").fetchone())


def setup(db):
    db.db.execute("CREATE TABLE IF NOT EXISTS venue_orders(client_id TEXT PRIMARY KEY,challenge_id INTEGER,stage TEXT,body TEXT)")
    db.db.execute("CREATE INDEX IF NOT EXISTS venue_pending ON venue_orders(challenge_id,stage)")
    db.db.execute("""CREATE TABLE IF NOT EXISTS venue_executions(
        client_id TEXT NOT NULL REFERENCES venue_orders, trade_id TEXT NOT NULL,
        payload TEXT NOT NULL, PRIMARY KEY(client_id,trade_id))""")
    # Two distinct exchange orders can fill in the same second. Paper keeps its
    # original bar uniqueness. Exchange fills have one summary per client ID.
    index = db.db.execute("SELECT sql FROM sqlite_master WHERE name='unique_fill'").fetchone()
    if index and " WHERE " not in index[0].upper():
        db.db.execute("DROP INDEX unique_fill")
        db.db.execute("""CREATE UNIQUE INDEX unique_fill ON fills(challenge_id,t,symbol,kind)
                         WHERE json_extract(data,'$.client_id') IS NULL""")
    db.db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS venue_fill_summary
                     ON fills(challenge_id,json_extract(data,'$.client_id'))
                     WHERE json_extract(data,'$.client_id') IS NOT NULL""")


def save(db, order, stage):
    order["stage"] = stage
    db.db.execute("UPDATE venue_orders SET stage=?,body=? WHERE client_id=?",
                  (stage, encode(order), order["client_id"]))


def pending(db, cid):
    row = db.db.execute(f"SELECT body FROM venue_orders WHERE challenge_id=? AND {OPEN} ORDER BY rowid LIMIT 1", (cid,)).fetchone()
    return json.loads(row[0]) if row else None


def unresolved(db):
    return [(r[0], json.loads(r[1])) for r in db.db.execute(
        f"SELECT challenge_id,body FROM venue_orders WHERE {OPEN} ORDER BY rowid")]


def enqueue(db, s, k, side, m, amount, why):
    if hosted_pending(db):
        db.record("system_events", s, "REJECT", "托管保护单待核对，禁止普通委托与保护单冲突", k)
        return
    tag = decision_tag(s, k, side, m)
    client = "sm" + tag["signal_id"][:28]
    if db.db.execute("SELECT 1 FROM venue_orders WHERE client_id=?", (client,)).fetchone():
        return
    if unresolved(db):
        db.record("system_events", s, "REJECT", "已有未核对委托，禁止新增订单", k, tag)
        return
    order = dict(client_id=client, symbol=k, side=side, amount=amount, reference=m["price"],
                 bar=m["time"], reason=why, stage="QUEUED", created_at=s["t"],
                 account_ref=s.get("account_ref"), portfolio_version=position_version(s), exchange=s["config"].get("exchange"),
                 environment=s["config"].get("execution"), product=s["config"].get("product"),
                 revision=s.get("revision", 0), slippage_budget=m.get("slip", 0.001),
                 calculation=m.get("calculation"), **tag)
    db.db.execute("INSERT INTO venue_orders VALUES(?,?,?,?)", (client, s["id"], "QUEUED", encode(order)))
    db.record("system_events", s, "QUEUED", "等待交易所执行前检查", k, {**tag, "client_id": client})


def number(value):
    try:
        n = Decimal(str(value))
        if n.is_finite():
            return n
    except ArithmeticError:
        pass
    raise ValueError("交易所回报含无效数值")


def receipt_symbol(o):
    return o["symbol"] + "/USDT" + (":USDT" if o.get("product") == "swap" else "")


def check_receipt_identity(order, o):
    """Reject conflicting identities even when a transport has already checked them.

    Older adapters may omit optional fields; they must still verify identity in
    lookup. An explicit contradiction must never reach the funds ledger.
    """
    info = order.get("info") or {}
    original = info.get("origClientOrderId") if isinstance(info, dict) else None
    clients = [v for v in (order.get("clientOrderId"), original) if v not in (None, "")]
    if ((clients and o["client_id"] not in clients)
            or (order.get("symbol") is not None and order["symbol"] != receipt_symbol(o))
            or (order.get("side") is not None and order["side"] != o["side"].lower())):
        raise ValueError("订单回报的客户端标识、交易对或方向与本地意图不一致")


def execution(trade, order, o):
    if (not str(trade.get("id") or "").strip() and trade.get("id") != 0
            or str(trade.get("order")) != str(order["id"])
            or trade.get("side") != o["side"].lower()
            or (trade.get("symbol") is not None and trade["symbol"] != receipt_symbol(o))):
        raise ValueError("成交标识、交易对或方向不一致")
    qty, price = number(trade.get("amount")), number(trade.get("price"))
    fees = trade.get("fees") or ([trade["fee"]] if trade.get("fee") else [])
    if qty <= 0 or price <= 0 or not fees:
        raise ValueError("缺少可核验的成交数量、价格或费用")
    costs = {}
    for f in fees:
        asset, cost = f.get("currency"), number(f.get("cost"))
        if not asset:
            raise ValueError("手续费币种缺失")
        if cost and (asset not in (o["symbol"], "USDT")
                     or (o.get("product") == "swap" and asset != "USDT")):
            raise ValueError("第三币种手续费待核对，已阻止新单")
        costs[asset] = costs.get(asset, Decimal(0)) + cost
    return {"qty": str(qty.normalize()), "price": str(price.normalize()),
            "fees": {k: str(v.normalize()) for k, v in sorted(costs.items())}}


def apply_receipt(s, o, row):
    symbol = o["symbol"]
    qty = float(number(row["qty"]) * number(o["prepared"]["contract"]))
    price = float(row["price"])
    cost = qty * price
    base_fee = float(row["fees"].get(symbol, 0))
    quote_fee = float(row["fees"].get("USDT", 0))
    position = s["positions"].get(symbol)
    pnl = 0.0
    held = 0
    if o["side"] == "BUY":
        if position and position.get("opening_order") != o["client_id"]:
            raise ValueError("本地持仓归属与买单不一致")
        if qty <= base_fee or cost + quote_fee > s["cash"] + 1e-8:
            raise ValueError("成交回报超过策略资金或实际持仓不足")
        if not position:
            position = dict(qty=0, cost=0, high=price, opened=s["t"], opening_order=o["client_id"])
            s["positions"][symbol] = position
        position["qty"] += qty - base_fee
        position["cost"] += cost + quote_fee
        position.update(entry=position["cost"] / position["qty"], price=price, high=max(price, position["high"]))
        s["cash"] -= cost + quote_fee
        s["last_buy"] = s["t"]
    else:
        if not position or qty + base_fee > position["qty"] + max(1e-12, position["qty"] * 1e-9):
            raise ValueError("卖出回报超过策略持仓")
        held = s["t"] - position["opened"]
        fraction = min(1, (qty + base_fee) / position["qty"])
        basis = position["cost"] * fraction
        pnl = cost - quote_fee - basis
        s["realized"] += pnl
        s["cash"] += cost - quote_fee
        position["qty"] -= qty + base_fee
        position["cost"] -= basis
        if position["qty"] <= qty * 1e-10:
            del s["positions"][symbol]
    fee = quote_fee + base_fee * price
    slip = (price - o["reference"]) * (1 if o["side"] == "BUY" else -1) * qty
    s["fees"] += fee
    s["slippage"] += slip
    return dict(qty=qty, nominal=cost, fee=fee, slippage=slip, pnl=pnl, held=held)


def settle(db, s, o, order, trades):
    """Caller owns one transaction for receipts, ledger, position snapshot and order."""
    persisted = db.db.execute("SELECT stage,challenge_id FROM venue_orders WHERE client_id=?", (o["client_id"],)).fetchone()
    if not persisted:
        raise ValueError("本地订单意图缺失")
    if persisted[1] != s["id"]:
        raise ValueError("订单与当前会话不一致")
    if persisted[0] in FINAL:
        return True
    check_receipt_identity(order, o)
    status = order.get("status")
    if status not in ("open", "closed", "expired", "canceled", "rejected") or not order.get("id"):
        raise ValueError("交易所订单身份或状态未知")
    if o.get("exchange_id") and str(o["exchange_id"]) != str(order["id"]):
        raise ValueError("交易所订单编号发生变化")
    filled, requested = number(order.get("filled")), number(o["prepared"]["quantity"])
    if requested <= 0 or filled < 0 or filled > requested + Decimal("1e-12"):
        raise ValueError("交易所累计成交数量无效")
    o["exchange_id"] = str(order["id"])
    if order.get("amount") is not None and not math.isclose(number(order["amount"]), requested, rel_tol=1e-10):
        raise ValueError("交易所原始委托数量不符")
    prior = {r[0]: json.loads(r[1]) for r in db.db.execute(
        "SELECT trade_id,payload FROM venue_executions WHERE client_id=?", (o["client_id"],))}
    received = dict(prior)
    for trade in trades:
        key = str(trade.get("id"))
        new = execution(trade, order, o)
        if key in received and new != received[key]:
            raise ValueError("相同成交 ID 的回报发生冲突")
        received[key] = new
    total = sum((number(r["qty"]) for r in received.values()), Decimal(0))
    if not math.isclose(total, filled, rel_tol=1e-10, abs_tol=1e-14):
        raise ValueError("累计成交与可核对逐笔明细不符")
    aggregate = o.get("receipt") or dict(qty=0, nominal=0, fee=0, slippage=0, pnl=0, held=0,
        client_id=o["client_id"], exchange_id=o["exchange_id"], side=o["side"], reason=o["reason"],
        venue=s["config"]["exchange"], environment=s["config"]["execution"],
        decision_id=o.get("decision_id"), signal_id=o.get("signal_id"), calculation=o.get("calculation"))
    for key, row in received.items():
        if key in prior:
            continue
        delta = apply_receipt(s, o, row)
        for field in ("qty", "nominal", "fee", "slippage", "pnl"):
            aggregate[field] += delta[field]
        aggregate["held"] = delta["held"]
        db.db.execute("INSERT INTO venue_executions VALUES(?,?,?)", (o["client_id"], key, encode(row)))
    terminal = status != "open"
    if not terminal:
        stage = "PARTIALLY_FILLED" if filled else "SUBMITTED"
    elif filled:
        stage = "FILLED" if math.isclose(filled, requested, rel_tol=1e-10) else "PARTIAL_CANCELLED"
    else:
        stage = "REJECTED" if status == "rejected" else "CANCELLED"
    if received:
        aggregate.update(price=aggregate["nominal"]/aggregate["qty"], cash=s["cash"],
                         stage=stage, trade_ids=list(received))
        if "fill_row" in o:
            db.db.execute("UPDATE fills SET data=? WHERE id=? AND challenge_id=?",
                          (encode(aggregate), o["fill_row"], s["id"]))
        else:
            o["fill_row"] = db.record("fills", s, o["side"], o["reason"], o["symbol"], aggregate)
        o["receipt"] = aggregate
    if stage != persisted[0] or len(prior) != len(received):
        db.record("system_events", s, stage, "已按交易所回报核对", o["symbol"],
                  {"client_id": o["client_id"], "decision_id": o.get("decision_id"),
                   "filled": str(filled), "trade_count": len(received)})
    save(db, o, stage)
    return terminal
