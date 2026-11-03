"""Shared configuration recommendations and execution-valid numeric checks."""
import math

# Recommendations guide the UI. They never clamp a valid user's choice.
RECOMMENDED = {
    "capital": ("策略资金 USDT", 10, 100000),
    "target": ("单笔目标仓位 %", 5, 50),
    "risk_per_trade_pct": ("单笔风险预算 / 净资产 %", 0.25, 2),
    "interval": ("扫描间隔秒数", 5, 120),
    "decision_interval": ("决策间隔秒数", 60, 3600),
    "candidates": ("候选数量", 5, 50),
    "slots": ("同时持仓数量", 1, 5),
    "utilization": ("最大资金利用率 %", 30, 95),
    "concentration": ("单币持仓上限 %", 10, 60),
    "stop": ("止损 %", 0.5, 8),
    "profit": ("止盈 %", 1, 20),
    "trail": ("移动止损 %", 0.5, 10),
    "cooldown": ("开仓冷却秒数", 15, 600),
    "breaker": ("回撤熔断 %", 5, 50),
    "loss_limit": ("累计亏损停机 %", 1, 90),
    "fee": ("单边手续费 %", 0.001, 2),
    "strict_min": ("软件最小订单金额 USDT", 1, 10000),
    "frame": ("主决策回看周期分钟", 1, 15),
    "trend": ("高级趋势回看周期分钟", 5, 15),
}
INTEGERS = {"interval", "decision_interval", "candidates", "slots", "cooldown", "frame", "trend"}
PERCENTAGES = {"target", "risk_per_trade_pct", "utilization", "concentration", "stop",
               "trail", "breaker", "loss_limit", "fee"}


def validate_parameters(config):
    for key, (name, _, _) in RECOMMENDED.items():
        if key not in config:
            continue
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(name + "必须为有限数值，不能为布尔值或文本")
        if key in INTEGERS and (value != int(value) or value > 2147483647):
            raise ValueError(name + "必须为可处理的整数")
        allow_zero = key in ("cooldown", "fee")
        if value < 0 or (not allow_zero and value == 0):
            raise ValueError(name + ("不能为负数" if allow_zero else "必须大于零"))
        if key in PERCENTAGES and (value > 100 or (key in ("stop", "trail", "fee") and value == 100)):
            raise ValueError(name + "超出有效百分比范围")
    frame, trend = config["frame"], config["trend"]
    if trend < frame:
        raise ValueError("高级趋势周期不得短于主决策周期")
    if max(75, 3 * frame + 1, 3 * trend + 1, 5 * frame) > 240:
        raise ValueError("所选周期超出当前 240 根分钟线窗口，请缩短周期")
    if config["slots"] > config["candidates"]:
        raise ValueError("同时持仓数量不能超过候选数量")
    if not math.isfinite(config["capital"] * 100):
        raise ValueError("资金数值过大，无法可靠计算仓位")


def recommendations(config):
    return [
        {"field": key, "name": name, "value": config[key], "low": low, "high": high,
         "message": f"{name}超出推荐范围 {low}–{high}，保留当前值，请确认其交易影响"}
        for key, (name, low, high) in RECOMMENDED.items()
        if key in config and not low <= config[key] <= high
    ]
