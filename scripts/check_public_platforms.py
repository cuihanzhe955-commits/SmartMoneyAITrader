"""Optional official public REST probe. No credentials/account endpoints or writes."""
import argparse,json,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from market.discovery import public_client,evaluate,DiscoveryQuery
from execution.venue import Venue


def probe(name):
    c=public_client(name);c.timeout=4000
    result=dict(exchange=name,checked_at=int(time.time()),account_access=False,order_writes=False,
                real_funds_verified=False)
    try:
        markets=c.load_markets()
        ticks=c.fetch_tickers(params={"type":"spot"})
        report=evaluate(c,markets,ticks,DiscoveryQuery(exchange=name,budget=10,limit=5),time.time())
        v=Venue.__new__(Venue);v.client=c;v.name=name;v.env="public";v.swap=False
        bars=v.bars(["BTC"])
        result.update(status="public_read_completed",spot_scope=report["scope"],eligible=report["eligible"],
            rejection_counts=report["rejection_counts"],closed_btc_candles=len(bars.get("BTC",[])),
            candle_errors=dict(bars.errors),quote_source_time_verified=any(r.get("source_timestamp") is not None for r in report["rows"]))
    except Exception as err:
        regional="451" in str(err) or "restricted location" in str(err).lower()
        result.update(status="blocked" if regional else "unavailable",reason="地区访问限制，未绕过" if regional else type(err).__name__+" · 公开接口未完成读取")
    finally:c.close()
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True);args=parser.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(probe,("okx","binance","gate")))
    output=dict(public_only=True,platform_account_integration=False,results=results)
    Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(output,ensure_ascii=False))
