NAMES = ("动量突破", "趋势跟随", "均值回归", "成交量异常", "波动率策略")


def ema(values, n):
    v = values[0]
    alpha = 2 / (n + 1)
    for x in values[1:]:
        v += alpha * (x - v)
    return v


def enrich(rows, m, c):
    closes = [r[4] for r in rows]
    changes = [b - a for a, b in zip(closes[-15:-1], closes[-14:])]
    up = sum(max(x, 0) for x in changes)
    down = sum(max(-x, 0) for x in changes)
    rsi = 100 * up / (up + down) if up + down else 50
    atr = (
        sum(
            max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4]))
            for a, b in zip(rows[-15:-1], rows[-14:])
        )
        / 14
    )
    fast, slow = ema(closes[-60:], 9), ema(closes[-60:], 21)
    signals = [
        m["breakout"] >= 0 and m["momentum"] > 0.001,
        fast > slow and m["trend"] > 0.002,
        rsi < 35 and closes[-1] > closes[-2],
        m["relative"] > 1.6 and m["momentum"] > 0,
        atr / m["price"] > 0.004 and m["momentum"] > 0.003,
    ]
    votes = [n for n, v in zip(NAMES, signals) if v and n in c.get("strategies", NAMES)]
    m.update(rsi=rsi, atr=atr, ema9=fast, ema21=slow, signals=votes)
    if c.get("profile") == "normal":
        m["buy"] = (
            m["valid"]
            and len(votes) >= min(2, len(c.get("strategies", NAMES)))
            and m["score"] >= 55
        )
    elif "strategies" in c:
        m["buy"] = m["buy"] and bool(votes)
    return m
