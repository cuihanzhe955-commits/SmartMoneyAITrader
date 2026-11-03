import math


def clip(x):
    return max(0, min(1, x))


def analyze(rows, t, c):
    required = max(75, 3 * c["frame"] + 1, 3 * c["trend"] + 1, 5 * c["frame"])
    if len(rows) < required or not 0 <= t - rows[-1][0] < 120:
        raise ValueError("行情过期或预热不足")
    if any(b[0] - a[0] != 60 for a, b in zip(rows, rows[1:])) or any(
        not all(math.isfinite(v) for v in b)
        or not 0 < b[3] <= min(b[1], b[4]) <= max(b[1], b[4]) <= b[2]
        or b[5] < 0
        for b in rows
    ):
        raise ValueError("行情缺口或价格异常")
    f = c["frame"]
    n = c["trend"]
    last = rows[-1]
    p = last[4]
    momentum = p / rows[-1 - 3 * f][4] - 1
    trend = p / rows[-1 - 3 * n][4] - 1
    volume = sum(x[5] for x in rows[-f:]) / f
    relative = volume / max(1, sum(x[5] for x in rows[-5 * f : -f]) / (4 * f))
    vol = sum(x[2] / x[3] - 1 for x in rows[-15:]) / 15
    breakout = p / max(x[2] for x in rows[-21:-1]) - 1
    factors = [
        clip(0.5 + momentum * 35),
        clip(relative / 2),
        clip(0.5 + trend * 20),
        clip(vol * 90),
        clip(0.5 + breakout * 45),
    ]
    slip = 0.0002 + min(0.025, vol * 0.12)
    score = round(
        100 * sum(x * w for x, w in zip(factors, c["weights"])) / sum(c["weights"])
        - min(15, slip * 800),
        1,
    )
    valid = volume >= 5000 and slip < 0.008
    trigger = {
        "快速动量": momentum > 0.002,
        "突破追踪": breakout > 0 and relative > 1.1,
        "综合狂飙": momentum > 0.001 and (relative > 1 or breakout > 0),
    }[c["preset"]]
    return dict(
        price=p,
        time=last[0],
        volume=volume,
        relative=relative,
        momentum=momentum,
        trend=trend,
        vol=vol,
        breakout=breakout,
        slip=slip,
        score=score,
        valid=valid,
        buy=valid and trigger and trend > 0 and score >= 60,
    )
