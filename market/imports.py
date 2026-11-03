import csv
import io
import math
import re
from collections import defaultdict
from bisect import bisect_right


def parse_csv(text):
    """One close timestamp (UTC seconds) per closed, one-minute candle."""
    rows = defaultdict(list)
    for line, r in enumerate(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))), 2):
        try:
            symbol = r["symbol"].upper().removesuffix("/USDT")
            if not re.fullmatch("[A-Z0-9]{2,15}", symbol):
                raise ValueError()
            t = int(r["timestamp"])
            o, h, l, c, v = (
                float(r[k]) for k in ("open", "high", "low", "close", "quote_volume")
            )
            if (
                t % 60
                or t <= 0
                or not all(math.isfinite(x) for x in (o, h, l, c, v))
                or not 0 < l <= min(o, c) <= max(o, c) <= h
                or v < 0
            ):
                raise ValueError()
            a = rows[symbol]
            if a and t - a[-1][0] != 60:
                raise ValueError()
            a.append([t, o, h, l, c, v])
        except (KeyError, ValueError, TypeError):
            raise ValueError(f"CSV 第 {line} 行字段、价格或连续性错误") from None
    if not rows or len(rows) > 50 or min(map(len, rows.values())) < 76:
        raise ValueError("需要 1–50 个币种，每个至少 76 根连续分钟线")
    start = max(a[74][0] for a in rows.values())
    end = min(a[-1][0] for a in rows.values())
    if end <= start:
        raise ValueError("公共回放窗口不足")
    return dict(rows), start, end


def window(rows, t):
    def clip(a):
        n = bisect_right(a, t, key=lambda x: x[0])
        return a[max(0, n - 240) : n]

    return {k: clip(a) for k, a in rows.items()}
