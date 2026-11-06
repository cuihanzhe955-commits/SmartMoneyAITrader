"""Synchronous paper execution. The caller commits fills, cash and cursor together."""

from execution.order_state import lifecycle


def fill(db, s, symbol, side, m, amount, reason, order_id=None, calculation=None, order_tag=None):
    c = s["config"]
    buying = side == "BUY"
    ref = m["price"]
    price = m.get("execution_price", ref * (1 + m["slip"] if buying else 1 - m["slip"]))
    qty = m.get("execution_quantity", amount / price if buying else s["positions"][symbol]["qty"])
    nominal = qty * price
    fee = nominal * c["fee"] / 100
    slip = abs(ref - price) * qty
    pnl = 0
    held = 0
    if buying:
        s["cash"] -= nominal + fee
        s["positions"][symbol] = dict(
            qty=qty, entry=price, price=ref, high=ref, opened=s["t"], cost=nominal + fee
        )
        s["last_buy"] = s["t"]
    else:
        p = s["positions"].pop(symbol)
        held = s["t"] - p["opened"]
        pnl = nominal - fee - p["cost"]
        s["realized"] += pnl
        s["cash"] += nominal - fee
    assert s["cash"] >= -1e-9
    s["fees"] += fee
    s["slippage"] += slip
    data = dict(
        side=side,
        reference=ref,
        price=price,
        qty=qty,
        nominal=nominal,
        fee=fee,
        slippage=slip,
        cash=s["cash"],
        pnl=pnl,
        held=held,
        reason=reason,
        states=lifecycle("CREATED", "APPROVED", "SUBMITTED", "FILLED"),
    )
    if calculation is not None:
        data["calculation"] = calculation
    if order_tag:
        data.update(order_tag)
    if order_id is None:
        oid = db.record("simulated_orders", s, "FILLED", reason, symbol, data)
    else:
        from events.store import encode

        oid = order_id
        db.db.execute(
            "UPDATE simulated_orders SET kind='FILLED',data=? WHERE id=?",
            (encode(data), oid),
        )
    data["order_id"] = oid
    db.record("fills", s, side, reason, symbol, data)
    db.record(
        "system_events",
        s,
        "FILLED",
        "模拟买入成交" if buying else "模拟卖出成交",
        symbol,
        data,
    )
    return oid
