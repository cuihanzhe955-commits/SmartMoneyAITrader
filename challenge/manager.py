import math
import time
from challenge.report import build_report
from market.feeds import START, historical, public
from challenge.config import VERSION
from strategy.rules import analyze
from execution.broker import fill
from execution.order_state import lifecycle
from risk.limits import equity, allowance, finalize
from events.store import encode

from challenge.validation import config
from risk.parameters import recommendations
from execution.identity import decision_tag


def execute(db, s, symbol, side, metrics, amount, reason):
    if s["config"].get("execution", "paper") == "paper":
        if "profile" in s["config"]:
            from execution.paper_queue import queue

            return queue(db, s, symbol, side, metrics, amount, reason)
        return fill(db, s, symbol, side, metrics, amount, reason)
    from execution.live import enqueue

    return enqueue(db, s, symbol, side, metrics, amount, reason)


def create(db, body, *, validated=None):
    prev = db.load()
    if prev and prev["lifecycle_status"] not in ("COMPLETED", "STOPPED"):
        raise ValueError("请先结束当前挑战")
    c = validated if validated is not None else config(body)
    cid = db.db.execute("INSERT INTO challenges(state) VALUES('{}')").lastrowid
    t = START if c["source"] == "history" else int(time.time())
    s = dict(
        id=cid,
        config=c,
        version=VERSION,
        lifecycle_status="CREATED",
        current_activity="WAITING",
        t=t,
        start=t,
        deadline=t + 86400,
        anchor=0,
        last_scan=0,
        last_buy=0,
        heartbeat=0,
        delay=None,
        cash=c["capital"],
        positions={},
        fees=0,
        slippage=0,
        realized=0,
        peak=c["capital"],
        max_dd=0,
        dd=0,
        breaker=False,
        radar=[],
        symbol="",
        latest="等待手动开始",
        next_scan=t,
        pending=False,
    )
    db.db.execute("INSERT INTO challenge_configs VALUES(?,?)", (cid, encode(c)))
    db.record("system_events", s, "CREATED", "交易会话已创建，等待启动")
    warnings = recommendations(c)
    if warnings:
        db.record("system_events", s, "CONFIG_WARNING", "已保存超出推荐范围的用户配置",
                  data={"warnings": warnings})
    db.save(s)
    return s


from challenge.clock import market_time


def snapshot(db, s):
    nav = equity(s)
    s["peak"] = max(s["peak"], nav)
    s["dd"] = 100 * (1 - nav / s["peak"])
    s["max_dd"] = max(s["dd"], s["max_dd"])
    db.record(
        "portfolio_snapshots",
        s,
        "NAV",
        data={"nav": nav, "cash": s["cash"], "dd": s["dd"]},
    )
    db.db.execute("DELETE FROM positions WHERE challenge_id=?", (s["id"],))
    db.db.executemany(
        "INSERT INTO positions VALUES(?,?,?)",
        [(s["id"], k, encode(v)) for k, v in s["positions"].items()],
    )
    return nav


def decision(db, s, k, m, action, reason, amount=0, calculation=None):
    payload = dict(
        strategy=s["config"]["preset"],
        version=s["version"],
        config_id=s["id"],
        metrics=m,
        strength=m["score"],
        amount=amount,
        risks="分钟收盘估值、价差估计和流动性风险",
        exits={x: s["config"][x] for x in ("stop", "trail", "profit")},
    )
    if calculation:
        payload["calculation"] = calculation
    payload.update(decision_tag(s, k, action, m))
    db.record("decisions", s, action, reason, k, payload)
    db.record("system_events", s, action, reason, k, payload)
    s["latest"] = k + " · " + reason
    s["symbol"] = k


def finish(db, s, stop=False):
    from execution.paper_queue import cancel

    for k in list(s.get("paper_pending", {})):
        cancel(db, s, k, "会话结束")
    c = s["config"]
    fresh = s.get("feed_valid", False) and all(
        any(r["symbol"] == k and 0 <= s["t"] - r["time"] < 120 for r in s["radar"])
        for k in s["positions"]
    )
    s["pending"] = bool(s["positions"]) and not fresh
    if (
        not stop
        and fresh
        and c["settlement"] == "close"
        and c.get("execution", "paper") == "paper"
    ):
        for k in list(s["positions"]):
            m = next(r for r in s["radar"] if r["symbol"] == k)
            if c.get("paper_rules") == "venue":
                from execution.paper_queue import round_step, ROUND_DOWN

                rule = c["precision_rules"].get(k)
                qty = s["positions"][k]["qty"]
                if rule:
                    price = round_step(
                        m["price"] * (1 - m["slip"]), rule["tick"], ROUND_DOWN
                    )
                if (
                    not rule
                    or qty < rule["minimum"]
                    or qty * price < max(c["strict_min"], rule["min_cost"])
                ):
                    s["pending"] = True
                    db.record(
                        "system_events", s, "REJECT", "结算数量或金额低于交易规则", k
                    )
                    continue
                m = dict(m, execution_price=price)
            decision(db, s, k, m, "EXIT", "挑战结算平仓")
            fill(db, s, k, "SELL", m, 0, "挑战结算平仓")
    nav = snapshot(db, s)
    s["lifecycle_status"] = "STOPPED" if stop else "COMPLETED"
    s["current_activity"] = "WAITING"
    s["next_scan"] = None
    db.record(
        "system_events",
        s,
        s["lifecycle_status"],
        "结算待确认" if s["pending"] else "停止并保留仓位" if stop else "挑战已结算",
    )
    report = build_report(db, s, nav)
    db.record("reports", s, "REPORT", data=report)
    db.save(s)


def protective_exit(position, price, config):
    if price <= position["entry"] * (1 - config["stop"] / 100):
        return "固定止损"
    if price <= position["high"] * (1 - config["trail"] / 100):
        return "移动止损"
    if price >= position["entry"] * (1 + config["profit"] / 100):
        return "策略止盈"
    return ""


def scan(db, s, t, rows=None, manage=True, *, advice=None, block_entries=False, order_pending=False):
    c = s["config"]
    s["t"] = t
    s["heartbeat"] = int(time.time())
    s["current_activity"] = "SCANNING"
    try:
        feed = (
            rows
            if rows is not None
            else (historical(t) if c["source"] == "history" else public(t))
        )
        ranked = []
        for k, bars in feed.items():
            try:
                metrics = analyze(bars, t, c)
                if "profile" in c:
                    from strategy.ensemble import enrich

                    enrich(bars, metrics, c)
                ranked.append(dict(symbol=k, **metrics))
            except ValueError as e:
                db.record("system_events", s, "REJECT", str(e), k)
        if not ranked or set(s["positions"]) - {m["symbol"] for m in ranked}:
            raise ValueError("持仓估值或市场行情不可用")
    except Exception as e:
        s["feed_valid"] = False
        s["lifecycle_status"] = "DATA_STALE"
        s["delay"] = (
            t - max((m["time"] for m in s["radar"]), default=t) if s["radar"] else None
        )
        s["latest"] = str(e)
        s["next_scan"] = t + c["interval"]
        db.record("system_events", s, "ERROR", str(e))
        db.save(s)
        return
    s["feed_valid"] = True
    s["current_activity"] = "ANALYZING"
    s["lifecycle_status"] = "RUNNING"
    ranked.sort(key=lambda m: (-m["score"], m["symbol"]))
    s["radar"] = ranked
    s["last_scan"] = t
    s["delay"] = max(t - m["time"] for m in ranked)
    s["next_scan"] = t + c["interval"]
    db.record("market_snapshots", s, "SCAN", data={"radar": ranked})
    db.record("system_events", s, "SCAN", f"已扫描 {len(ranked)} 个现货交易对")
    db.record(
        "system_events",
        s,
        "ANALYZING",
        "已计算并排序候选评分",
        data={"ranking": [(m["symbol"], m["score"]) for m in ranked]},
    )
    for m in ranked:
        p = s["positions"].get(m["symbol"])
        if p:
            p["price"] = m["price"]
            p["high"] = max(p["high"], p["price"])
    nav = equity(s)
    s["peak"] = max(nav, s["peak"])
    dd = (1 - nav / s["peak"]) * 100
    if dd >= c["breaker"] or (1 - nav / c["capital"]) * 100 >= c.get("loss_limit", 101) or s["breaker"]:
        if not s["breaker"]:
            db.record("system_events", s, "BREAKER", "组合回撤触发熔断")
        s["breaker"] = True
        s["lifecycle_status"] = "PAUSED"
        s["latest"] = "组合回撤触发熔断"
        block_entries = True
    # Exit proposals have deterministic priority. A symbol cannot re-enter in this scan.
    from execution.paper_queue import drain, cancel

    if manage:
        drain(db, s, ranked, block_buys=block_entries or order_pending)
    elif s["breaker"]:
        for k in list(s.get("paper_pending", {})):
            cancel(db, s, k, "回撤熔断")
    ordered = sorted(ranked, key=lambda m: m["symbol"] not in s["positions"])
    candidates = {m["symbol"] for m in ranked[: int(c["candidates"])]}
    for m in ordered if manage else []:
        k = m["symbol"]
        p = s["positions"].get(k)
        reason = ""
        seen = s.setdefault("decided_bars", {})
        protection = protective_exit(p, m["price"], c) if p else ""
        ai_for_symbol = advice and advice["symbol"] == k and advice["action"] in ("BUY", "SELL")
        if order_pending:
            continue
        if not protection and not ai_for_symbol and m["time"] - seen.get(k, 0) < c.get("decision_interval", 60):
            continue
        seen[k] = m["time"]
        if ai_for_symbol and not protection:
            m = dict(m, ai=advice, proposal=advice.get("_stamp"))
        if p:
            if protection:
                reason = protection
                m = dict(m, protective=True)
            elif m["trend"] < -0.004:
                reason = "趋势反转"
            elif m["momentum"] < -0.004:
                reason = "动量衰减"
            elif t - p["opened"] >= 3600:
                reason = "时间止损"
            elif advice and advice["symbol"] == k and advice["action"] == "SELL":
                reason = advice["reason"]
            if reason:
                decision(db, s, k, m, "SELL", reason)
                execute(db, s, k, "SELL", m, 0, reason)
            else:
                decision(db, s, k, m, "HOLD", "持仓监控，退出条件未触发")
        elif (
            k in candidates
            and not block_entries
            and (
                m["valid"] and advice["symbol"] == k and advice["action"] == "BUY"
                if advice
                else m["buy"]
            )
        ):
            s["current_activity"] = "RISK_CHECK"
            amount, why, caps = allowance(s, c, m)
            if advice:
                ai_limit = nav * advice["fraction"]
                if amount and ai_limit < amount:
                    amount, why, caps = finalize(
                        caps, ai_limit, "限制原因：AI 提案仓位",
                        {"name": "AI 提案仓位", "amount": ai_limit, "pct": 100 * advice["fraction"]},
                    )
            if amount and amount < c.get("strict_min", 1):
                amount, why = 0, "未达到订单金额下限"
            finalize(caps, amount, why)
            decision(
                db,
                s,
                k,
                m,
                "BUY",
                (
                    advice["reason"]
                    if advice
                    else "入场信号：" + "、".join(m.get("signals", []) or [c["preset"]])
                ),
                amount,
                calculation=caps["calculation"],
            )
            db.record(
                "risk_checks", s, "APPROVED" if amount else "REJECT", why, k, caps
            )
            db.record("system_events", s, "RISK_CHECK", why, k, caps)
            if amount:
                s["current_activity"] = "EXECUTING"
                execute(db, s, k, "BUY", dict(m, calculation=caps["calculation"]), amount, why)
            else:
                decision(db, s, k, m, "REJECT", why, calculation=caps["calculation"])
                if c.get("execution","paper")!="paper":
                    continue
                db.record(
                    "simulated_orders",
                    s,
                    "REJECTED",
                    why,
                    k,
                    {"states": lifecycle("CREATED", "REJECTED")},
                )
        else:
            decision(
                db,
                s,
                k,
                m,
                "HOLD" if m["valid"] else "REJECT",
                (
                    "等待下一次 AI 提案或 AI 故障暂停开仓"
                    if block_entries
                    else (
                        "AI 未提议买入此币种"
                        if advice and m["valid"]
                        else "入场条件不足" if m["valid"] else "流动性或成本未通过"
                    )
                ),
            )
    snapshot(db, s)
    s["current_activity"] = "MONITORING" if s["positions"] else "WAITING"
    db.save(s)


def action(db, s, cmd):
    st = s["lifecycle_status"]
    if cmd == "start" and st == "CREATED":
        s["anchor"] = time.time()
        s["lifecycle_status"] = "INITIALIZING"
        if s["config"]["source"] == "public":
            s["start"] = s["t"] = s["next_scan"] = int(s["anchor"])
            s["deadline"] = s["start"] + 86400
    elif cmd == "pause" and st in ("RUNNING", "DATA_STALE", "INITIALIZING"):
        from execution.paper_queue import cancel

        for k in list(s.get("paper_pending", {})):
            cancel(db, s, k, "用户暂停")
        s["lifecycle_status"] = "PAUSED"
        s["next_scan"] = None
    elif (
        cmd == "resume" and st in ("PAUSED", "ERROR", "DATA_STALE") and not s["breaker"]
    ):
        now = market_time(s)
        if now >= s["deadline"]:
            s["t"] = now
            finish(db, s)
            return
        if s["cash"] < 0 or db.entries(
            "simulated_orders", s["id"], 1, kind="SUBMITTED"
        ):
            raise ValueError("账户或订单状态异常")
        s["next_scan"] = now
        s["lifecycle_status"] = "INITIALIZING"
    elif cmd in ("end", "stop") and st not in ("STOPPED", "COMPLETED"):
        s["t"] = market_time(s) if st != "CREATED" else s["start"]
        finish(db, s, cmd == "stop")
        return
    else:
        raise ValueError("当前状态不允许此操作")
    db.record(
        "system_events",
        s,
        s["lifecycle_status"],
        {
            "start": "开始初始化",
            "pause": "用户暂停，估值暂停",
            "resume": "重新验证行情与账户",
        }[cmd],
    )
    db.save(s)
