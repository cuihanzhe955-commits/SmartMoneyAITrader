"""Public, read-only spot discovery. No account, permissions or order calls."""
import math
import re
import threading
import time
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Literal
import ccxt
from pydantic import BaseModel,ConfigDict,Field,field_validator
from execution.market_rules import spot_rules


class DiscoveryQuery(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    exchange: Literal["okx","binance","gate"]="okx"
    budget: float=Field(10,gt=0,strict=True)
    fee_pct: float=Field(.1,ge=0,lt=100,strict=True)
    minimum: float=Field(1,ge=0,strict=True)
    min_volume: float=Field(1_000_000,ge=0,strict=True)
    max_spread_pct: float=Field(.3,gt=0,le=100,strict=True)
    max_change_pct: float=Field(50,gt=0,strict=True)
    search: str=Field("",max_length=32)
    whitelist: list[str]=Field(default_factory=list,max_length=200)
    blacklist: list[str]=Field(default_factory=list,max_length=200)
    limit: int=Field(25,ge=1,le=200,strict=True)

    @field_validator("whitelist","blacklist")
    @classmethod
    def pairs(cls,values):
        result=[]
        for value in values:
            value=value.strip().upper()
            if "/" not in value:value+="/USDT"
            if not re.fullmatch(r"[A-Z0-9]{1,30}/USDT",value):raise ValueError("名单请填写币种或 USDT 现货交易对")
            if value not in result:result.append(value)
        return result


def public_client(name):
    c=getattr(ccxt,name)({"enableRateLimit":True,"timeout":8000,"maxRetriesOnFailure":0,
        "options":{"defaultType":"spot","fetchCurrencies":False,"fetchMarkets":{"types":["spot"]}}})
    c.session.trust_env=False
    # Gate's load_markets checks this capability rather than options.fetchCurrencies.
    # Spot discovery needs instrument metadata only, not chain/funding metadata.
    c.has["fetchCurrencies"]=False
    return c


def number(v):return type(v) in (int,float) and math.isfinite(v)


def evaluate(client,markets,tickers,q,now,received_at=None):
    rows=[];counts=Counter();scope=0;matched=0
    for symbol,m in markets.items():
        if not isinstance(m,dict) or m.get("spot") is not True or m.get("quote")!="USDT":continue
        if symbol!=m.get("symbol") or not re.fullmatch(r"[A-Z0-9]{1,30}/USDT",symbol):continue
        scope+=1
        if q.search.strip().upper() not in symbol:continue
        if q.whitelist and symbol not in q.whitelist:counts["未在白名单"]+=1;continue
        if symbol in q.blacklist:counts["黑名单"]+=1;continue
        matched+=1
        r=dict(symbol=symbol,eligible=False,reasons=[],source_timestamp=None,received_at=now if received_at is None else received_at)
        try:
            if q.exchange=="gate":
                info=m.get("info") or {}
                # Native Gate merges margin metadata into spot.active. Require the
                # explicit spot status and minimum, not that merged capability.
                minimum=info.get("min_base_amount")
                if info.get("trade_status")!="tradable":raise ValueError("Gate 现货交易状态未确认")
                if minimum is None or not Decimal(str(minimum)).is_finite() or Decimal(str(minimum))<=0:
                    raise ValueError("Gate 现货最小数量未确认")
            rules=spot_rules(m,client.precisionMode,symbol)
            r["rules"]=rules
            ticker=tickers.get(symbol)
            if not isinstance(ticker,dict) or ticker.get("symbol")!=symbol:raise ValueError("批量行情缺失或标的不符")
            bid,ask,last,volume,high,low=(ticker.get(k) for k in ("bid","ask","last","quoteVolume","high","low"))
            stamp=ticker.get("timestamp")
            if not number(stamp) or not -2<=now-stamp/1000<=120:raise ValueError("行情时间缺失、过期或时钟偏差")
            r["source_timestamp"]=stamp/1000
            if not all(number(v) and v>0 for v in (bid,ask,last)) or bid>ask:raise ValueError("买卖盘口无效")
            if not number(volume) or volume<0:raise ValueError("成交额缺失或无效")
            if not all(number(v) and v>0 for v in (high,low)) or low>high:raise ValueError("24小时高低价缺失或无效")
            change=ticker.get("percentage")
            if not number(change):
                opened=ticker.get("open")
                if not number(opened) or opened<=0:raise ValueError("24小时涨跌幅不可核验")
                change=(last/opened-1)*100
            spread=(ask/bid-1)*100;amplitude=(high-low)/last*100
            if not all(number(v) for v in (change,spread,amplitude)):
                raise ValueError("行情派生指标数值无效")
            r.update(bid=bid,ask=ask,last=last,quote_volume=volume,spread_pct=spread,change_pct=change,amplitude_pct=amplitude)
            if volume<q.min_volume:r["reasons"].append("成交额不足")
            if spread>q.max_spread_pct:r["reasons"].append("价差超限")
            if abs(change)>q.max_change_pct:r["reasons"].append("涨跌幅异常")
            price=Decimal(client.price_to_precision(symbol,str(Decimal(str(ask))*Decimal("1.001"))))
            if not price.is_finite() or price<=0 or abs(price/Decimal(str(ask))-1)>Decimal(".01"):
                raise ValueError("精度处理后限价偏离盘口")
            gross=Decimal(str(q.budget));fee=Decimal(str(q.fee_pct))/100
            available=gross/(1+fee)
            quantity=Decimal(client.amount_to_precision(symbol,str(available/price)))
            if not quantity.is_finite() or quantity<=0:raise ValueError("预算不足以满足数量精度")
            cost=quantity*price;total=cost*(1+fee)
            r["budget"]=dict(allocated=q.budget,quantity=float(quantity),price=float(price),notional=float(cost),
                fee_reserved=float(cost*fee),total=float(total),unused=float(gross-total))
            if total>gross:r["reasons"].append("精度处理超出预算")
            if cost<Decimal(str(q.minimum)):r["reasons"].append("低于软件最小金额")
            for field,value in (("amount",quantity),("price",price),("cost",cost)):
                rule=m["limits"].get(field,{})
                if ((rule.get("min") is not None and value<Decimal(str(rule["min"]))) or
                    (rule.get("max") is not None and value>Decimal(str(rule["max"])))):
                    r["reasons"].append("不满足交易所"+{"amount":"数量","price":"价格","cost":"金额"}[field]+"限额")
            r["eligible"]=not r["reasons"]
        except ccxt.InvalidOrder:
            r["reasons"].append("预算不足以满足数量精度")
        except (InvalidOperation,ZeroDivisionError,OverflowError):
            r["reasons"].append("精度或预算数值无法核验")
        except ValueError as e:r["reasons"].append(str(e))
        for reason in r["reasons"]:counts[reason]+=1
        rows.append(r)
    rows.sort(key=lambda r:(not r["eligible"],-r.get("amplitude_pct",-1),r["symbol"]))
    return dict(read_only=True,changes_sessions=False,executable=False,exchange=q.exchange,
        scope=scope,matched=matched,eligible=sum(r["eligible"] for r in rows),shown=min(len(rows),q.limit),
        rejection_counts=dict(counts),rows=rows[:q.limit],filters=q.model_dump(),
        note="仅公开行情与预算研究，不是订单授权。成交额是流动性代理，未核验盘口深度；运行中会话仍使用原监控池。")


class Discovery:
    def __init__(self,factory=None,clock=time.time,monotonic=time.monotonic):
        self.factory,self.clock,self.monotonic=factory or public_client,clock,monotonic
        self.cache={};self.lock=threading.Lock()

    def run(self,q):
        if not self.lock.acquire(blocking=False):raise ValueError("公开行情研究正在进行，请稍后重试")
        try:
            now=self.monotonic();item=self.cache.get(q.exchange)
            if not item or now-item["market_at"]>=600:
                c=self.factory(q.exchange)
                try:markets=c.load_markets()
                except Exception:
                    c.close();raise
                item=dict(client=c,markets=markets,market_at=now,ticker_at=-math.inf)
                previous=self.cache.get(q.exchange)
                if previous:previous["client"].close()
                self.cache[q.exchange]=item
            cached=now-item["ticker_at"]<60
            if not cached:
                tickers=item["client"].fetch_tickers(params={"type":"spot"})
                if not isinstance(tickers,dict):raise ValueError("批量行情格式无法核验")
                item.update(tickers=tickers,ticker_at=self.monotonic(),received_at=self.clock())
            result=evaluate(item["client"],item["markets"],item["tickers"],q,self.clock(),item["received_at"])
            return dict(result,source="CCXT / "+q.exchange+" 官方公开现货 API",cached=cached,
                received_at=item["received_at"],cache_age_sec=max(0,self.monotonic()-item["ticker_at"]),
                refresh_interval_sec=60,market_refresh_interval_sec=600)
        except ccxt.BaseError as e:
            if "451" in str(e) or "restricted location" in str(e).lower():
                raise ValueError("平台限制了当前地区访问；研究已停止，不切换域名或绕过限制") from None
            if isinstance(e,ccxt.RateLimitExceeded):raise ValueError("公开接口限频，未重试；请稍后重试") from None
            raise ValueError("公开行情读取失败，未使用过期缓存，请检查平台连接") from None
        except ValueError:
            raise
        except Exception:
            raise ValueError("公开市场元数据无法解析，研究已停止；未修改交易会话") from None
        finally:self.lock.release()

    def close(self):
        with self.lock:
            for item in self.cache.values():item["client"].close()
            self.cache.clear()
