"""Shared normalized spot rules for research and production admission."""
import math
import ccxt


def spot_rules(market, mode, symbol):
    if market.get("active") is not True or market.get("spot") is not True:
        raise ValueError(f"{symbol} 不是可交易的现货交易对")
    precision = market.get("precision") or {}
    if not isinstance(precision, dict):
        raise ValueError(f"{symbol} 数量或价格精度格式无效，无法完成规则验收")
    valid = lambda n: (isinstance(n, (int, float)) and not isinstance(n, bool)
                       and math.isfinite(n))
    limits = market.get("limits")
    if not isinstance(limits, dict):
        raise ValueError(f"{symbol} 限额规则不完整，无法完成规则验收")
    for field, name in (("amount", "数量"), ("price", "价格"), ("cost", "金额")):
        rule = limits.get(field, {})
        if not isinstance(rule, dict):
            raise ValueError(f"{symbol} {name}限额格式无效，无法完成规则验收")
        low, high = rule.get("min"), rule.get("max")
        if ((low is not None and (not valid(low) or low < 0)) or
                (high is not None and (not valid(high) or high <= 0))):
            raise ValueError(f"{symbol} {name}限额数值无效，无法完成规则验收")
        if low is not None and high is not None and low > high:
            raise ValueError(f"{symbol} {name}上下限矛盾，无法完成规则验收")
    minimum = limits.get("amount", {}).get("min")
    if not valid(minimum) or minimum <= 0:
        raise ValueError(f"{symbol} 缺少有效的最小下单数量，无法完成规则验收")
    for field in ("amount", "price"):
        value = precision.get(field)
        if (not valid(value) or
                not ((mode == ccxt.TICK_SIZE and value > 0) or
                     (mode == ccxt.DECIMAL_PLACES and value >= 0 and value == int(value)))):
            raise ValueError(f"{symbol} 数量或价格精度不完整，无法完成规则验收")
    cost = limits.get("cost", {}).get("min")
    return dict(symbol=symbol, min_quantity=minimum,
                quantity_precision=precision["amount"], price_precision=precision["price"],
                precision_mode=mode, min_notional=cost)
