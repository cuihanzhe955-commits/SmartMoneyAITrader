import math


def equity(s):
    return s["cash"] + sum(p["qty"] * p["price"] for p in s["positions"].values())


def finalize(caps, amount, reason, extra_limit=None):
    """Keep historical numeric cap keys and attach an auditable calculation."""
    detail = caps["calculation"]
    if extra_limit is not None:
        detail["limits"].append(extra_limit)
    detail["final_amount"] = amount
    detail["estimated_fee"] = amount * detail.get("fee_pct", 0) / 100
    detail["final_pct"] = 100 * amount / detail["nav"] if detail["nav"] > 0 else 0
    detail["reason"] = reason
    return amount, reason, caps


def allowance(s, c, m):
    nav = equity(s)
    risk_pct = c.get("risk_per_trade_pct", 1)
    fee = c["fee"] / 100
    slip = m["slip"]
    caps = {"calculation": {
        "version": 1, "nav": nav if math.isfinite(nav) else 0,
        "target_pct": c["target"], "risk_per_trade_pct": risk_pct,
        "compatibility_default": "risk_per_trade_pct" not in c,
        "limits": [], "precision_status": "待执行器按交易所规则核验",
    }}
    detail = caps["calculation"]
    inputs = (nav, s["cash"], risk_pct, fee, slip, c["stop"], c["target"],
              c["concentration"], c["utilization"])
    if (not all(type(v) in (float, int) and math.isfinite(v) for v in inputs)
            or nav <= 0 or s["cash"] < 0 or not 0 < risk_pct <= 100
            or not 0 <= fee < 1 or not 0 <= slip < 1 or not 0 < c["stop"] < 100):
        caps["calculation"] = {"version": 1, "nav": 0, "limits": [],
                               "precision_status": "风控输入无效，尚未检查"}
        return finalize(caps, 0, "净资产、余额、风险预算或交易成本无效")
    invested = nav - s["cash"]
    loss_rate = c["stop"] / 100 + 2 * (fee + slip)
    raw = {
        "目标仓位": nav * c["target"] / 100,
        "单币上限": nav * c["concentration"] / 100,
        "资金利用率": nav * c["utilization"] / 100 - invested,
        "可用余额": s["cash"] / (1 + fee),
        "风险预算": nav * (risk_pct / 100) / loss_rate,
    }
    if not all(math.isfinite(value) for value in raw.values()):
        return finalize(caps, 0, "仓位计算溢出，无法可靠执行")
    caps.update(raw)
    effective = {name: max(0, value) / (1 + slip) for name, value in raw.items()}
    amount = min(effective.values())
    detail.update(
        risk_budget=nav * risk_pct / 100, loss_rate=loss_rate,
        fee_pct=c["fee"], slippage_pct=100 * slip,
        cost_reserve_factor=1 + slip, software_min=c.get("strict_min", 1),
        estimated_fee=amount * fee,
        formula="风险上限 = 净资产×风险预算% ÷（止损% + 双边手续费 + 双边滑点）；各上限再除以 1+滑点预留",
        limits=[{"name": name, "raw_amount": raw[name], "amount": value,
                 "pct": 100 * value / nav} for name, value in effective.items()],
        binding_limits=[name for name, value in effective.items() if value == amount],
    )
    if len(s["positions"]) >= c["slots"]:
        return finalize(caps, 0, "持仓数量已达上限")
    if s["t"] - s["last_buy"] < c["cooldown"]:
        return finalize(caps, 0, "新开仓冷却中")
    if amount <= 0:
        return finalize(caps, 0, "资金利用率或可用资金不足")
    if amount < c.get("strict_min", 1):
        return finalize(caps, 0, "低于配置的最小订单金额")
    return finalize(caps, amount, "限制原因：" + "、".join(detail["binding_limits"]))
