"""Read-only indicator method comparison on the shipped public historical archive."""
from market.feeds import historical, START, SYMBOLS
from strategy.rules import analyze
from strategy.ensemble import enrich, NAMES
from strategy.indicators import standard
from terminal.config import Session

METHODS = {
    "rsi": ("RSI 14", "最近14次涨跌幅汇总", "Wilder 14周期平滑；横盘返回50"),
    "atr": ("ATR 14", "最近14次真实波幅均值", "Wilder 14周期平滑"),
    "ema9": ("EMA 9", "最近60根，以首价初始化", "可用窗口内以9根均值初始化"),
    "ema21": ("EMA 21", "最近60根，以首价初始化", "可用窗口内以21根均值初始化"),
}


def compare(symbol="BTC", offset_minute=0):
    if symbol not in SYMBOLS or type(offset_minute) is not int or not 0 <= offset_minute <= 1440:
        raise ValueError("请选择归档支持的币种与 0 至 1440 的整数分钟偏移")
    as_of = START + offset_minute * 60
    rows = historical(as_of)[symbol]
    if rows[-1][0] > as_of:
        raise ValueError("研究窗口包含尚未收盘的数据")
    config = Session(consent=True).settings()
    metrics = analyze(rows, as_of, config)
    legacy = enrich(rows, metrics.copy(), config)
    reference = standard(rows)
    for value in reference.values():
        if value is None:
            raise ValueError("指标预热不足，无法比较")
    standard_signals = [
        metrics["breakout"] >= 0 and metrics["momentum"] > .001,
        reference["ema9"] > reference["ema21"] and metrics["trend"] > .002,
        reference["rsi"] < 35 and rows[-1][4] > rows[-2][4],
        metrics["relative"] > 1.6 and metrics["momentum"] > 0,
        reference["atr"] / metrics["price"] > .004 and metrics["momentum"] > .003,
    ]
    votes = [name for name, yes in zip(NAMES, standard_signals) if yes]
    standard_buy = metrics["valid"] and len(votes) >= 2 and metrics["score"] >= 55
    return dict(symbol=symbol, as_of=as_of, start=rows[0][0], bars=len(rows),
        source="项目附带 Binance 公开历史归档", timeframe="已收盘1分钟线", profile="固定普通规则实验配置",
        read_only=True, changes_sessions=False, production_method="legacy", engine_changed=False,
        reference_method="Wilder RSI/ATR + SMA-seeded EMA; TA-Lib 0.8.3 对照",
        comparisons=[dict(key=k,name=meta[0],legacy=legacy[k],standard=reference[k],
                          delta=reference[k]-legacy[k],legacy_method=meta[1],standard_method=meta[2])
                     for k,meta in METHODS.items()],
        signals=dict(legacy=legacy["signals"],standard=votes,legacy_buy=legacy["buy"],standard_buy=standard_buy),
        bars_preview=[dict(time=r[0],open=r[1],high=r[2],low=r[3],close=r[4]) for r in rows[-100:]],
        note="计算口径对照不证明哪种策略更盈利；当前运行策略保持原口径，不应用此研究结果下单。")
