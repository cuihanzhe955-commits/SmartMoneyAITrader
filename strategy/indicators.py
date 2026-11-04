"""Finite, causal standard indicator reference for research; legacy engine unchanged.

EMA uses an SMA seed; RSI/ATR use Wilder smoothing. None marks warm-up.
No TA-Lib runtime dependency and no fallback that silently changes semantics.
"""
import math


def period_value(period):
    if type(period) is not int or not 2 <= period <= 100000:
        raise ValueError("指标周期必须为 2 至 100000 的整数")


def finite_series(values):
    result = list(values)
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in result):
        raise ValueError("指标输入包含缺失、无穷或非数值；不能用猜测值填补")
    return result


def ema(values, period):
    period_value(period); values=finite_series(values)
    out=[None]*len(values)
    if len(values)<period:return out
    previous=sum(values[:period])/period
    out[period-1]=previous
    for i in range(period,len(values)):
        previous+=(values[i]-previous)*2/(period+1)
        out[i]=previous
    return out


def rsi(values, period=14):
    period_value(period); values=finite_series(values)
    out=[None]*len(values)
    if len(values)<=period:return out
    changes=[b-a for a,b in zip(values,values[1:])]
    gain=sum(max(x,0) for x in changes[:period])/period
    loss=sum(max(-x,0) for x in changes[:period])/period
    def score():return 100*gain/(gain+loss) if gain+loss else 50.0
    out[period]=score()
    for i in range(period+1,len(values)):
        change=values[i]-values[i-1]
        gain=(gain*(period-1)+max(change,0))/period
        loss=(loss*(period-1)+max(-change,0))/period
        out[i]=score()
    return out


def atr(highs,lows,closes,period=14):
    period_value(period)
    highs,lows,closes=map(finite_series,(highs,lows,closes))
    if not len(highs)==len(lows)==len(closes):raise ValueError("ATR 高低收盘序列长度不同")
    if any(not 0 < lo <= c <= hi for hi,lo,c in zip(highs,lows,closes)):
        raise ValueError("ATR 行情价格关系无效")
    out=[None]*len(closes)
    if len(closes)<=period:return out
    tr=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    previous=sum(tr[:period])/period
    out[period]=previous
    for i in range(period+1,len(closes)):
        previous=(previous*(period-1)+tr[i-1])/period
        out[i]=previous
    return out


def standard(rows):
    closes=[r[4] for r in rows]
    last=lambda values: values[-1] if values else None
    return dict(rsi=last(rsi(closes)),atr=last(atr([r[2] for r in rows],[r[3] for r in rows],closes)),
                ema9=last(ema(closes,9)),ema21=last(ema(closes,21)))
