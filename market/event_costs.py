"""Read-only cost research for documented v1, taker-only, exponent-1 curves.

Formula source: https://docs.polymarket.com/trading/fees
No orders, fills, account balances, simulation ledger or actual-fee claims.
"""
from decimal import Decimal, ROUND_DOWN
from pydantic import Field
from market.event_details import QuoteQuery, decimal, book_snapshot
from market.event_units import unit_evidence, precision_envelope

CLOB_INFO = "https://clob.polymarket.com/clob-markets/"
SHARE_STEP = Decimal("0.000001")
ROUND_RESERVE = Decimal("0.0001")


class CostQuery(QuoteQuery):
    shares: float = Field(10, gt=0, le=1_000_000, strict=True, allow_inf_nan=False)
    budget: float = Field(10, gt=0, le=1_000_000_000, strict=True, allow_inf_nan=False)
    max_slippage_pct: float = Field(1, ge=0, le=100, strict=True, allow_inf_nan=False)


def curve_parameters(info, market):
    if market.get("protocol_version") != "v1":
        raise ValueError("成本研究当前仅支持明确标记v1的CTF市场；v2或未知版本暂不估算")
    if not isinstance(info, dict) or not isinstance(info.get("t"), list) or len(info["t"]) != 2:
        raise ValueError("官方费用参数缺少唯一的结果映射")
    actual = {}
    for item in info["t"]:
        if not isinstance(item, dict) or not isinstance(item.get("t"), str) or not isinstance(item.get("o"), str) or item["t"] in actual:
            raise ValueError("费用参数的结果Token映射无效")
        actual[item["t"]] = item["o"]
    if actual != {o["token_id"]: o["name"] for o in market["outcomes"]}:
        raise ValueError("费用参数与官方市场的结果Token或名称不符")
    fd = info.get("fd")
    if not isinstance(fd, dict) or fd.get("to") is not True:
        raise ValueError("尚未核验该市场仅向taker计费的参数")
    rate = decimal(fd.get("r"), "费用曲线系数")
    exponent = decimal(fd.get("e"), "费用曲线指数")
    if not 0 <= rate <= 1 or exponent != 1:
        raise ValueError("费用曲线系数或指数不在已核验模型范围；未使用默认公式")
    enabled = market.get("fees_enabled")
    if type(enabled) is not bool or (not enabled and rate != 0):
        raise ValueError("Gamma费用开关与费用曲线无法一致核验")
    minimum, tick = decimal(info.get("mos"), "费用接口最小值"), decimal(info.get("mts"), "费用接口价格档位")
    if minimum <= 0 or not 0 < tick <= 1:
        raise ValueError("费用接口交易规则无效")
    return dict(rate=rate, minimum=minimum, tick=tick)


def estimate_cost(query, market, info, raw_book, now):
    params = curve_parameters(info, market)
    units = unit_evidence(market, params)
    outcome = market["outcomes"][query.outcome_index]
    snapshot = book_snapshot(raw_book, market, outcome["token_id"], now)
    if not snapshot["quote_available"]:
        raise ValueError("成本研究需要有效双边盘口，不以单边报价推断可成交成本")
    if (params["tick"] != decimal(raw_book["tick_size"], "盘口价格档位") or
            params["minimum"] != decimal(raw_book["min_order_size"], "盘口最小值")):
        raise ValueError("费用接口与盘口交易规则不一致")
    asks = sorted((decimal(x["price"], "卖盘价格"), decimal(x["size"], "卖盘数量")) for x in raw_book["asks"])
    requested, budget = decimal(query.shares, "目标份额"), decimal(query.budget, "研究预算")
    desired = requested.quantize(SHARE_STEP, rounding=ROUND_DOWN)
    if desired <= 0:
        raise ValueError("目标份额低于本成本研究的百万分之一份额计算步长")
    best = asks[0][0]
    cap = min(Decimal(1), best*(1+decimal(query.max_slippage_pct,"滑点预算")/100))
    quantity = gross = fee = reserve = Decimal(0)
    precision_low = precision_high = Decimal(0)
    fills = []; limits = ["目标份额按研究步长向下取整"] if desired != requested else []
    for price, depth in asks:
        if quantity >= desired:break
        if price > cap:
            limits.append("价格超出滑点上限")
            break
        # Documented exponent-1 taker fee per share, not base_fee_bps/10000.
        per_fee = params["rate"]*price*(1-price)
        padding = ROUND_RESERVE if per_fee else Decimal(0)
        available = budget-gross-fee-reserve-padding
        if available <= 0:
            limits.append("含费与取整预留后预算不足")
            break
        affordable = (available/(price+per_fee)).quantize(SHARE_STEP,rounding=ROUND_DOWN)
        wanted = min(desired-quantity,depth)
        take = min(wanted,affordable).quantize(SHARE_STEP,rounding=ROUND_DOWN)
        if take <= 0:
            limits.append("预算或盘口数量低于计算步长")
            break
        level_fee = take*per_fee
        low, high = precision_envelope(level_fee)
        precision_low += low; precision_high += high
        quantity += take;gross += take*price;fee += level_fee;reserve += padding
        fills.append(dict(price=float(price),shares=float(take),gross=float(take*price),model_fee=float(level_fee),rounding_reserve=float(padding),
            precision_scenario_low=float(low),precision_scenario_high=float(high)))
        if affordable < wanted:
            limits.append("研究预算限制")
            break
    if quantity < desired and not any(reason != "目标份额按研究步长向下取整" for reason in limits):
        limits.append("本次快照深度或研究数量步长限制")
    if quantity < params["minimum"]:limits.append("保守最小份额检查未通过")
    if gross < params["minimum"]:limits.append("保守最小名义金额检查未通过")
    complete = quantity == desired
    feasible = quantity > 0 and quantity >= params["minimum"] and gross >= params["minimum"]
    total = gross+fee+reserve
    if total > budget:
        raise ValueError("成本计算超出研究预算，拒绝结果")
    return dict(provider="polymarket",product="event",market_id=market["market_id"],condition_id=market["condition_id"],
        title=market["title"],slug=market["slug"],market_ends_at=market.get("ends_at"),resolution_description=market.get("resolution_source"),
        replay_input=dict(schema_version=1,market=market,
            info={k:info[k] for k in ("t","fd","mos","mts")},
            book={k:raw_book[k] for k in ("market","asset_id","timestamp","hash","bids","asks","min_order_size","tick_size")}),
        token_id=outcome["token_id"],outcome=outcome["name"],source_timestamp=snapshot["source_timestamp"],book_hash=snapshot["book_hash"],received_at=now,
        protocol_version="v1",curve_source=CLOB_INFO+market["condition_id"],book_source=snapshot["source"],
        model="documented_taker_exponent_1",fee_formula="shares * rate * price * (1-price), summed per depth level",
        fee_rate=float(params["rate"]),fee_exponent=1,fee_curve_verified=True,transaction_fee_verified=False,
        unit_evidence=units, precision_scenario_low=float(precision_low),precision_scenario_high=float(precision_high),
        precision_scenario="Assumes one modeled depth level is one match; not a bound on actual aggregated transaction fees",
        cost_unit="USDC reference units from official fee model",collateral_asset_verified=False,
        requested_shares=query.shares,rounded_requested_shares=float(desired),modeled_shares=float(quantity),unfilled_shares=float(desired-quantity),
        requested_budget=query.budget,modeled_gross=float(gross),modeled_fee=float(fee),rounding_reserve=float(reserve),
        modeled_total=float(total),remaining_budget=float(budget-total),
        average_price=float(gross/quantity) if quantity else None,price_cap=float(cap),best_ask=float(best),
        modeled_slippage_pct=float((gross/quantity/best-1)*100) if quantity else None,
        complete_fill_model=complete,requested_goal_exact=desired==requested,research_feasible=feasible,limits=limits,
        minimum_rule_value=float(params["minimum"]),minimum_policy="Conservative shares AND notional checks; native minimum unit not accepted for execution",
        depth_fills=fills[:20],modeled_level_count=len(fills),depth_rows_truncated=len(fills)>20,
        rounding_policy="Each modeled depth level reserves an extra 0.0001 reference USDC when fee is nonzero; not a claim about actual rounding",
        quantity_step=str(SHARE_STEP),simulation_ready=False,execution_enabled=False,
        notice="仅逐档成本研究，不创建模拟或真实成交；未验证抵押资产、真实扣费、gas、返佣或最终可成交性")
