"""Read-only market adapters. Bars are closed one-minute spot candles."""

import csv
import io
import json
import math
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen

DATA = Path(__file__).resolve().parents[1] / "data"
START = 1722816000  # 2024-08-05 00:00 UTC
SYMBOLS = ("BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "ADA")


def bar(row):
    return (
        int(row[0]) // 1000 + 60,
        *map(float, (row[1], row[2], row[3], row[4], row[7])),
    )


@lru_cache
def history(symbol):
    rows = []
    for path in sorted(DATA.glob(symbol + "USDT-*.zip")):
        with zipfile.ZipFile(path) as z:
            rows.extend(
                bar(r)
                for r in csv.reader(io.StringIO(z.read(z.namelist()[0]).decode()))
            )
    if len(rows) != 2880 or any(b[0] - a[0] != 60 for a, b in zip(rows, rows[1:])):
        raise ValueError("历史行情缺失或时间不连续")
    return rows


def historical(t):
    end = 1440 + (t - START) // 60
    return {s: history(s)[end - 240 : end] for s in SYMBOLS}


def public(t):
    def fetch(s):
        url = (
            "https://data-api.binance.vision/api/v3/klines?interval=1m&limit=241&symbol="
            + s
            + "USDT"
        )
        with urlopen(url, timeout=5) as r:
            rows = [bar(v) for v in json.load(r)]
        return s, [v for v in rows if v[0] <= t][-240:]

    with ThreadPoolExecutor(8) as pool:
        return dict(pool.map(fetch, SYMBOLS))
