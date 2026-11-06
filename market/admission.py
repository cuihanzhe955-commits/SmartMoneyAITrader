"""Dynamic public-paper admission, followed by independent risk and fill checks."""
import math
import re
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import ccxt
from pydantic import BaseModel, ConfigDict, Field, field_validator
from market.discovery import DiscoveryQuery
from market.pool import plan
from risk.limits import allowance


class ScannerConfig(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    limit:int=Field(25,ge=1,le=200,strict=True)
    min_volume:float=Field(1_000_000,ge=0,strict=True)
    max_spread_pct:float=Field(.3,gt=0,le=100,strict=True)
    max_change_pct:float=Field(50,gt=0,strict=True)
    max_slippage_pct:float=Field(.5,ge=0,lt=100,strict=True)
    search:str=Field("",max_length=32)
    whitelist:list[str]=Field(default_factory=list,max_length=200)
    blacklist:list[str]=Field(default_factory=list,max_length=200)

    @field_validator("whitelist","blacklist")
    @classmethod
    def pairs(cls, values):
        return DiscoveryQuery.pairs(values)


def finite(v):return type(v) in (int,float) and math.isfinite(v)


def query_for(s):
    c=s["config"];f=ScannerConfig(**c.get("scanner",{}))
    budget,_,_=allowance(s,c,{"slip":f.max_slippage_pct/100})
    if budget<=0:return None
    return DiscoveryQuery(exchange=c["exchange"],budget=float(budget),fee_pct=c["fee"],
        minimum=c["strict_min"],**f.model_dump(exclude={"max_slippage_pct"}))


def valid_rule(rule, symbol):
    if not isinstance(rule,dict) or rule.get("symbol")!=symbol:raise ValueError("交易规则标的不符")
    mode=rule.get("precision_mode")
    if mode not in (ccxt.TICK_SIZE,ccxt.DECIMAL_PLACES):raise ValueError("交易精度模式未支持")
    for key in ("quantity_precision","price_precision"):
        v=rule.get(key)
        if not finite(v) or (v<=0 if mode==ccxt.TICK_SIZE else v<0 or v!=int(v) or v>30):
            raise ValueError("数量或价格精度无效")
    if not finite(rule.get("min_quantity")) or rule["min_quantity"]<=0:raise ValueError("最小数量未确认")
    limits=rule.get("limits")
    if not isinstance(limits,dict):raise ValueError("交易限额未确认")
    for name in ("amount","price","cost"):
        item=limits.get(name,{})
        if not isinstance(item,dict):raise ValueError("交易限额无效")
        lo,hi=item.get("min"),item.get("max")
        if lo is not None and (not finite(lo) or lo<0):raise ValueError("最小限额无效")
        if hi is not None and (not finite(hi) or hi<=0):raise ValueError("最大限额无效")
        if lo is not None and hi is not None and lo>hi:raise ValueError("交易限额矛盾")
    return rule


def rounded(value, precision, mode, up=False):
    step=Decimal(str(precision)) if mode==ccxt.TICK_SIZE else Decimal(10)**-int(precision)
    return (Decimal(str(value))/step).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)*step


def executable(rule, symbol, reference, amount, slip, minimum, quantity=None):
    rule=valid_rule(rule,symbol)
    if not all(finite(v) and v>=0 for v in (reference,amount,slip,minimum)) or reference<=0 or slip>=1:
        raise ValueError("模拟执行价格或预算无效")
    buy=quantity is None
    price=rounded(reference*(1+slip if buy else 1-slip),rule["price_precision"],rule["precision_mode"],up=buy)
    if price<=0:raise ValueError("数量或价格精度不足")
    qty=rounded(Decimal(str(amount))/price if buy else quantity,rule["quantity_precision"],rule["precision_mode"])
    # Sell the full simulated holding only; never silently discard residual units.
    if not buy and qty!=Decimal(str(quantity)):raise ValueError("模拟持仓与当前数量步长不符，请保留残余并核对")
    cost=qty*price
    if qty<=0 or qty<Decimal(str(rule["min_quantity"])) or cost<Decimal(str(minimum)):
        raise ValueError("实际风控预算不足以满足最小数量或金额")
    for name,value in (("amount",qty),("price",price),("cost",cost)):
        limits=rule["limits"].get(name,{})
        if ((limits.get("min") is not None and value<Decimal(str(limits["min"]))) or
            (limits.get("max") is not None and value>Decimal(str(limits["max"])))):
            raise ValueError("实际订单不满足交易所"+name+"限额")
    if buy and cost>Decimal(str(amount)):raise ValueError("数量取整超出策略预算")
    return dict(quantity=float(qty),price=float(price),notional=float(cost),
                precision_status="公开规则校验通过；仅模拟撮合，不是平台成交")


def admit(report, s, now, pending=()):
    c=s["config"];f=ScannerConfig(**c.get("scanner",{}));q=query_for(s)
    accepted={};rejected={};status="waiting"
    header=(isinstance(report,dict) and report.get("exchange")==c["exchange"] and
            report.get("read_only") is True and report.get("changes_sessions") is False and
            isinstance(report.get("rows"),list) and isinstance(report.get("filters"),dict) and report["filters"].get("exchange")==c["exchange"])
    if header:
        status="ready"
        for row in report["rows"]:
            if not isinstance(row,dict):continue
            symbol=row.get("symbol","")
            if not isinstance(symbol,str) or not re.fullmatch(r"[A-Z0-9]{1,30}/USDT",symbol):continue
            try:
                if row.get("eligible") is not True:
                    reasons=row.get("reasons")
                    raise ValueError("；".join(reasons) if isinstance(reasons,list) and all(isinstance(r,str) for r in reasons) and reasons else "发现预检未通过")
                if q is None:raise ValueError("当前独立风控无可用开仓预算")
                stamp=row.get("source_timestamp")
                if not finite(stamp) or not 0<=now-stamp<120:raise ValueError("发现行情过期或来源时间不可核验")
                if f.whitelist and symbol not in f.whitelist:raise ValueError("未在白名单")
                if symbol in f.blacklist:raise ValueError("黑名单")
                if f.search.strip().upper() not in symbol:raise ValueError("不匹配搜索条件")
                bid,ask=row.get("bid"),row.get("ask")
                if not all(finite(v) and v>0 for v in (bid,ask)) or bid>ask:raise ValueError("盘口无效")
                if (ask/bid-1)*100>f.max_spread_pct:raise ValueError("价差超限")
                volume,change=row.get("quote_volume"),row.get("change_pct")
                if not finite(volume) or volume<f.min_volume:raise ValueError("成交额不足")
                if not finite(change) or abs(change)>f.max_change_pct:raise ValueError("涨跌幅异常")
                executable(row.get("rules"),symbol,ask,q.budget,f.max_slippage_pct/100,c["strict_min"])
                accepted[symbol[:-5]]=row
            except (ValueError,ArithmeticError) as err:rejected[symbol[:-5]]=str(err)
    elif report is not None:status="invalid_report"
    if q is None:status="risk_budget_unavailable"
    entries=list(accepted)[:f.limit]
    pool=plan(entries,s["positions"],pending,[x[:-5] for x in f.blacklist])
    return dict(pool,source="dynamic",admission=status,rejections=rejected,scope=report.get("scope",0) if header else 0,
                admitted_rows={k:accepted[k] for k in entries},execution_enabled=True)


def before_fill(s,k,m,amount,side):
    c=s["config"]
    if c.get("market_mode")!="dynamic":return None
    if c["execution"]!="paper" or c["source"]!="public" or c["product"]!="spot":
        raise ValueError("动态候选未授权用于该执行环境")
    if side=="BUY":
        pool=admit(s.get("discovery_report"),s,s["t"])
        row=pool["admitted_rows"].get(k)
        if row is None:raise ValueError("执行前动态准入失效或预算不足")
        if m["slip"]*100>c["scanner"]["max_slippage_pct"]:raise ValueError("实际滑点超过预算")
        if abs(m["price"]/row["ask"]-1)*100>c["scanner"]["max_change_pct"]:
            raise ValueError("分钟价格偏离发现盘口")
    rules=s.get("dynamic_rules",{}).get(k)
    if not isinstance(rules,dict) or not finite(rules.get("checked_at")) or not 0<=s["t"]-rules["checked_at"]<120:
        raise ValueError("模拟撮合缺少本平台有效交易规则")
    if (rules.get("exchange"),rules.get("product"))!=(c["exchange"],c["product"]):
        raise ValueError("交易规则来自其他平台或产品")
    return executable(rules["rule"],k+"/USDT",m["price"],amount,m["slip"],c["strict_min"],
                      None if side=="BUY" else s["positions"][k]["qty"])
