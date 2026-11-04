"""Read-only comparisons of external stop orders; never adopt or authorize them."""
from decimal import Decimal, InvalidOperation


def positive(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def audit_protection(state, inventory):
    positions = state["positions"]
    orders, issues, seen, candidates = [], [], set(), {}
    if inventory:
        issues.append("条件单尚未核验策略归属，不认定为交易所托管保护")
    for row in inventory:
        identity = str(row.get("algoId") or "")
        instrument = str(row.get("instId") or "")
        symbol = next((s for s in positions if instrument == s + "-USDT"), None)
        qty, trigger = positive(row.get("sz")), positive(row.get("slTriggerPx"))
        problems = []
        if not identity or identity in seen:
            problems.append("保护单标识缺失或重复")
        seen.add(identity)
        if row.get("instType") != "SPOT" or row.get("tdMode") != "cash":
            problems.append("不是已核对的现金现货订单")
        if row.get("ordType") != "conditional" or row.get("side") != "sell":
            problems.append("不是单向卖出止损条件单")
        if row.get("state") != "live":
            problems.append("保护单不是待触发状态，不能作为当前保护")
        if qty is None or trigger is None:
            problems.append("止损数量或触发价格无效")
        if str(row.get("slOrdPx")) != "-1" and positive(row.get("slOrdPx")) is None:
            problems.append("止损委托价格缺失或无效")
        if symbol is None:
            problems.append("交易对没有对应的策略持仓")
        if not problems:
            candidates.setdefault(symbol, []).append((identity, qty))
        issues.extend(instrument + "：" + problem for problem in problems)
        orders.append(dict(algo_id=identity, instrument=instrument, exchange_state=row.get("state"),
                           quantity=str(qty) if qty is not None else None,
                           stop_price=str(trigger) if trigger is not None else None, issues=problems))
    comparisons = []
    for symbol, position in positions.items():
        held = positive(position.get("qty"))
        rows = candidates.get(symbol, [])
        observed = sum((q for _, q in rows), Decimal(0))
        if held is None:
            status = "invalid_position"
            issues.append(symbol + "：策略持仓数量无效，无法核对")
        elif not rows:
            status = "missing"
            issues.append(symbol + "：未发现可比较的待触发止损单，仅本地止损尚不能代替托管保护")
        elif observed != held:
            status = "quantity_mismatch"
            issues.append(symbol + "：保护单数量 " + str(observed) + " 与持仓数量 " + str(held) + " 不一致")
        else:
            status = "quantity_matches_unverified"
        if len(rows) > 1:
            issues.append(symbol + "：存在多个候选保护单，需核对重复触发风险")
        comparisons.append(dict(symbol=symbol, position_quantity=str(held) if held is not None else None,
                                observed_stop_quantity=str(observed), algo_ids=[i for i, _ in rows], status=status))
    return dict(pending_algos=len(inventory), exchange_protection_verified=False,
                orders=orders, positions=comparisons, issues=issues)
