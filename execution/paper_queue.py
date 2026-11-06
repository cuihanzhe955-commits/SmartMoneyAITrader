"""Simulated latency is at least one closed bar. All pending orders are durable."""

from decimal import Decimal, ROUND_DOWN, ROUND_UP
from execution.broker import fill
from risk.limits import allowance, finalize
from events.store import encode
from execution.identity import decision_tag


def round_step(value, step, mode):
    return float(
        (Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=mode)
        * Decimal(str(step))
    )


def queue(db, s, k, side, m, amount, why):
    orders = s.setdefault("paper_pending", {})
    if k in orders:
        return
    tag = decision_tag(s, k, side, m)
    if not db.db.execute("INSERT OR IGNORE INTO paper_signal_keys VALUES(?,?)",
                         (tag["signal_id"], s["id"])).rowcount:
        return
    data = dict(
        side=side,
        nominal=amount,
        bar=m["time"],
        states=["CREATED", "APPROVED", "SUBMITTED"],
        **tag,
    )
    oid = db.record("simulated_orders", s, "SUBMITTED", why, k, data)
    orders[k] = dict(id=oid, side=side, amount=amount, bar=m["time"], reason=why, **tag)
    db.record(
        "system_events",
        s,
        "SUBMITTED",
        "模拟委托已提交，等待下一根有效收盘线",
        k,
        {"order_id": oid},
    )


def cancel(db, s, k, why, calculation=None):
    o = s["paper_pending"].pop(k)
    db.db.execute(
        "UPDATE simulated_orders SET kind='CANCELLED',summary=? WHERE id=?",
        (why, o["id"]),
    )
    db.record("system_events", s, "CANCELLED", why, k,
              {"order_id": o["id"], "calculation": calculation})


def drain(db, s, ranked, *, block_buys=False, only_sells=False):
    markets = {m["symbol"]: m for m in ranked}
    c = s["config"]
    for k, o in list(s.get("paper_pending", {}).items()):
        if only_sells and o["side"] != "SELL":
            continue
        if o["side"] == "BUY" and block_buys:
            cancel(db, s, k, "暂停新仓，撤回待成交模拟买单")
            continue
        if o.get("proposal"):
            from ai.coordinator import expired
            reason = expired(o["proposal"], s, s["t"], same_snapshot=False)
            if reason:
                cancel(db, s, k, reason)
                continue
        m = markets.get(k)
        if not m or m["time"] == o["bar"]:
            continue
        if not 0 < m["time"] - o["bar"] <= 120 or not m["valid"]:
            cancel(db, s, k, "委托超时或流动性不足")
            continue
        amount = o["amount"]
        buy = o["side"] == "BUY"
        calculation = None
        if buy:
            permitted, why, caps = allowance(s, c, m)
            amount = min(amount, permitted)
            if amount and amount < permitted:
                why = "限制原因：原委托金额"
            finalize(caps, amount, why, {"name": "原委托金额", "amount": o["amount"],
                                       "pct": 100 * o["amount"] / caps["calculation"]["nav"]
                                       if caps["calculation"]["nav"] > 0 else 0})
            calculation = caps["calculation"]
            if k in s["positions"] or amount < c["strict_min"]:
                finalize(caps, 0, "持仓已存在" if k in s["positions"] else why)
                db.record("risk_checks", s, "REJECT", calculation["reason"], k, caps)
                cancel(db, s, k, "执行前复核拒绝 · " + calculation["reason"], calculation)
                continue
        elif k not in s["positions"]:
            cancel(db, s, k, "持仓已变更")
            continue
        if c.get("market_mode") == "dynamic":
            from market.admission import before_fill
            try:
                result = before_fill(s, k, m, amount, o["side"])
                m = dict(m, execution_price=result["price"], execution_quantity=result["quantity"])
                if buy:
                    amount = result["notional"]
                    calculation.update(result)
                    why = "限制原因：动态市场规则与数量取整"
            except (ValueError, ArithmeticError) as err:
                if buy:
                    finalize(caps, 0, str(err))
                    db.record("risk_checks", s, "REJECT", str(err), k, caps)
                cancel(db, s, k, "动态执行前复核拒绝 · " + str(err), calculation)
                continue
        rules = c.get("precision_rules", {}).get(k)
        if c.get("paper_rules") == "venue":
            if not rules:
                if buy:
                    finalize(caps, 0, "无该标的归档精度")
                    db.record("risk_checks", s, "REJECT", calculation["reason"], k, caps)
                cancel(db, s, k, "无该标的归档精度", calculation)
                continue
            price = round_step(
                m["price"] * (1 + m["slip"] if buy else 1 - m["slip"]),
                rules["tick"],
                ROUND_UP if buy else ROUND_DOWN,
            )
            qty = round_step(
                amount / price if buy else s["positions"][k]["qty"],
                rules["step"],
                ROUND_DOWN,
            )
            if qty < rules["minimum"] or qty * price < max(
                c["strict_min"], rules["min_cost"]
            ):
                if buy:
                    calculation.update(quantity=qty, price=price, rule_step=rules["step"],
                                       rule_minimum=rules["minimum"], rule_min_cost=rules["min_cost"],
                                       precision_status="归档规则检查失败")
                    finalize(caps, 0, "交易所快照的数量或金额门槛未通过")
                    db.record("risk_checks", s, "REJECT", calculation["reason"], k, caps)
                cancel(db, s, k, "交易所快照的数量或金额门槛未通过", calculation)
                continue
            m = dict(m, execution_price=price)
            if buy:
                calculation.update(quantity=qty, price=price, rule_step=rules["step"],
                                   rule_minimum=rules["minimum"], rule_min_cost=rules["min_cost"],
                                   precision_status="通过交易所归档快照；尚非实时规则")
                if qty * price < amount:
                    why = "限制原因：数量步长取整"
                amount = qty * price
        if buy:
            if c.get("paper_rules") != "venue" and c.get("market_mode") != "dynamic":
                calculation["precision_status"] = "微资金模拟，不检查交易所数量精度"
            finalize(caps, amount, why)
            db.record("risk_checks", s, "APPROVED", why, k, caps)
        fill(db, s, k, o["side"], m, amount, o["reason"], order_id=o["id"],
             calculation=calculation, order_tag={k: o[k] for k in ("signal_id", "decision_id", "source") if k in o})
        del s["paper_pending"][k]
