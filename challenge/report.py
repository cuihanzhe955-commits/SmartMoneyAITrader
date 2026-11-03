from statistics import mean
from challenge.config import VERSION


def build_report(db, s, nav):
    c = s["config"]
    trades = db.entries("fills", s["id"])
    sells = [r for r in reversed(trades) if r["kind"] == "SELL"]
    wins = [r["data"]["pnl"] for r in sells if r["data"]["pnl"] > 0]
    losses = [-r["data"]["pnl"] for r in sells if r["data"]["pnl"] < 0]
    contrib = {}
    streak = maximum = 0
    durations = {"不足5分钟": 0, "5至30分钟": 0, "30分钟以上": 0}
    for r in sells:
        d = r["data"]
        k = r["symbol"]
        contrib[k] = contrib.get(k, 0) + d["pnl"]
        streak = streak + 1 if d["pnl"] < 0 else 0
        maximum = max(maximum, streak)
        durations[
            (
                "不足5分钟"
                if d["held"] < 300
                else "5至30分钟" if d["held"] < 1800 else "30分钟以上"
            )
        ] += 1
    for k, p in s["positions"].items():
        contrib[k] = contrib.get(k, 0) + p["qty"] * p["price"] - p["cost"]
    report = dict(
        challenge_id=s["id"],
        start=s["start"],
        end=s["t"],
        source=c["source"],
        version=VERSION,
        config=c,
        capital=c["capital"],
        nav=nav,
        return_pct=(nav / c["capital"] - 1) * 100,
        max_drawdown=s["max_dd"],
        fills=len(trades),
        win_rate=len(wins) / len(sells) if sells else None,
        payoff=mean(wins) / mean(losses) if wins and losses else None,
        fees=s["fees"],
        slippage=s["slippage"],
        best=max(sells, key=lambda r: r["data"]["pnl"], default=None),
        worst=min(sells, key=lambda r: r["data"]["pnl"], default=None),
        contributions=contrib,
        rejections=len(db.entries("risk_checks", s["id"], kind="REJECT")),
        loss_streak=maximum,
        holding_times=durations,
        pending=s["pending"],
        notice=(
            "真实交易所成交归因。策略预算净值不含账户其他活动、资金费和强平调整，以交易所账单为准。"
            if c.get("execution") == "live"
            else (
                "交易所模拟环境回报，不代表真实市场可实现的收益。"
                if c.get("execution") == "demo"
                else "全部结果来自模拟交易，不代表真实市场可实现的收益。"
            )
        ),
    )
    hours = {}
    for trade in trades:
        hour = f"{(trade['t']//3600)%24:02d}:00 UTC"
        hours[hour] = hours.get(hour, 0) + 1
    report["hourly_fills"] = hours
    if c.get("profile", "challenge") == "challenge":
        report["outcome"] = (
            "结算待确认"
            if s["pending"]
            else (
                "达到翻倍目标"
                if nav >= 2 * c["capital"]
                else (
                    "盈利未达目标"
                    if nav > c["capital"]
                    else "发生亏损" if nav < c["capital"] else "净值持平"
                )
            )
        )
    return report
