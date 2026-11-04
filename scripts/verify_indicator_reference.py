"""Explicit isolated TA-Lib POC; never imports user runtime or exchange credentials."""
import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def datasets():
    from market.feeds import historical, START
    cases={"archive_"+k:v for k,v in historical(START).items()}
    rng=random.Random(1046)
    values={"flat":[100.0]*240,"rising":[100+i*.5 for i in range(240)],
            "falling":[250-i*.5 for i in range(240)],
            "shock":[100.0]*120+[130.0]*120,
            "random":[100+rng.uniform(-5,5) for _ in range(240)]}
    for name,close in values.items():
        cases[name]=[(i*60,c,c+1,c-1,c,10000) for i,c in enumerate(close)]
    return cases


def verify(reference_path):
    sys.path.insert(0,str(Path(reference_path).resolve()))
    import numpy as np
    import talib
    if talib.__version__ != "0.8.3" or np.__version__ != "2.5.4":
        raise ValueError("参考环境版本不一致，请按 requirements-research.txt 建立隔离环境")
    from strategy.indicators import ema,rsi,atr
    from strategy.ensemble import enrich
    from strategy.rules import analyze
    from terminal.config import Session
    maxima={k:0.0 for k in ("ema9","ema21","rsi","atr")}
    checked=0;golden={};differences=[]
    for name,rows in datasets().items():
        close=np.array([r[4] for r in rows],dtype=np.float64)
        high=np.array([r[2] for r in rows],dtype=np.float64);low=np.array([r[3] for r in rows],dtype=np.float64)
        expected=dict(ema9=talib.EMA(close,9),ema21=talib.EMA(close,21),rsi=talib.RSI(close,14),atr=talib.ATR(high,low,close,14))
        actual=dict(ema9=ema(close.tolist(),9),ema21=ema(close.tolist(),21),rsi=rsi(close.tolist()),atr=atr(high.tolist(),low.tolist(),close.tolist()))
        for key,values in actual.items():
            for a,b in zip(values,expected[key]):
                if a is None:
                    assert math.isnan(b),(name,key,"warm-up")
                else:
                    assert math.isfinite(b) and math.isclose(a,float(b),rel_tol=1e-11,abs_tol=1e-10),(name,key,a,float(b))
                    maxima[key]=max(maxima[key],abs(a-float(b)));checked+=1
        if name in ("flat","rising","falling","shock","random"):
            golden[name]=dict(rows=rows,expected={k:[None if math.isnan(v) else float(v) for v in seq] for k,seq in expected.items()})
        if name.startswith("archive_"):
            config=Session(consent=True).settings()
            legacy=enrich(rows,analyze(rows,rows[-1][0],config),config)
            differences.append(dict(symbol=name[8:],legacy={k:legacy[k] for k in maxima},
                standard={k:float(expected[k][-1]) for k in maxima}))
    return dict(reference=dict(wrapper=talib.__version__,c_library=str(talib.__ta_version__),numpy=np.__version__),
                datasets=13,values_compared=checked,max_absolute_error=maxima,
                legacy_differences=differences,production_engine_changed=False),golden


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--reference-path",required=True);p.add_argument("--output",required=True);p.add_argument("--golden",required=True)
    args=p.parse_args();result,golden=verify(args.reference_path)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    Path(args.golden).write_text(json.dumps(dict(reference=result["reference"],cases=golden),separators=(",",":")),encoding="utf8")
    print(json.dumps({k:v for k,v in result.items() if k!="legacy_differences"},ensure_ascii=False))
