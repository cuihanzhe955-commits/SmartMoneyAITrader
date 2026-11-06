"""Bound public books and resolution evidence; never orders or wallet operations."""
from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import math
import re
from threading import Event, Lock
import time
from pydantic import BaseModel, ConfigDict, Field
from market.predictions import ENDPOINT, normalize, public_get, source_time

BOOK = "https://clob.polymarket.com/book"
FEE = "https://clob.polymarket.com/fee-rate"
RESOLUTION = "https://data-api.polymarket.com/v2/resolutions"


class MarketSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    market_id: str = Field(pattern=r"^[1-9][0-9]{0,29}$")


class QuoteQuery(MarketSelector):
    outcome_index: int = Field(0, ge=0, le=1, strict=True)


def decimal(value, name):
    if type(value) not in (str, int, float) or len(str(value)) > 100:
        raise ValueError(name + "数值格式无效")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or not math.isfinite(float(result)):
            raise ValueError(name + "数值非有限数")
        if abs(result.as_tuple().exponent) > 18:
            raise ValueError(name + "数值精度超出研究读取范围")
        return result
    except InvalidOperation:
        raise ValueError(name + "数值无法核验") from None


def timestamp(value):
    parsed = source_time(value)
    if parsed is not None:
        return parsed
    if type(value) not in (str, int, float):
        return None
    try:
        number = float(value)
        # Recognize absolute Unix seconds/milliseconds, never relative offsets.
        if 1e12 <= number < 1e14:
            number /= 1000
        return number if math.isfinite(number) and 1e9 <= number < 1e11 else None
    except (ValueError, OverflowError):
        return None


def book_snapshot(raw, market, token, now):
    condition = raw.get("market") if isinstance(raw, dict) else None
    if not isinstance(condition, str) or condition.lower() != market["condition_id"] or raw.get("asset_id") != token:
        raise ValueError("盘口的条件或结果 Token 与当前市场不符")
    stamp = timestamp(raw.get("timestamp"))
    if stamp is None or not 0 <= now - stamp < 30:
        raise ValueError("盘口源时间缺失、过期或本机时钟不一致")
    book_hash = raw.get("hash")
    if not isinstance(book_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{32,128}", book_hash):
        raise ValueError("盘口快照哈希缺失或无效")
    tick = decimal(raw.get("tick_size"), "价格档位")
    minimum = decimal(raw.get("min_order_size"), "最小份额")
    if not 0 < tick <= 1 or minimum <= 0:
        raise ValueError("盘口交易规则无效")
    sides = {}
    for side in ("bids", "asks"):
        levels = raw.get(side)
        if not isinstance(levels, list) or len(levels) > 5000:
            raise ValueError("盘口深度格式或规模无法核验")
        seen, parsed = set(), []
        for level in levels:
            if not isinstance(level, dict):
                raise ValueError("盘口档位格式无效")
            price, size = decimal(level.get("price"), "档位价格"), decimal(level.get("size"), "档位数量")
            if not 0 < price <= 1 or size <= 0 or price % tick or price in seen:
                raise ValueError("盘口价格、数量、精度或重复档位无效")
            seen.add(price); parsed.append((price, size))
        parsed.sort(reverse=side == "bids")
        sides[side] = parsed
    bid = sides["bids"][0][0] if sides["bids"] else None
    ask = sides["asks"][0][0] if sides["asks"] else None
    if bid is not None and ask is not None and bid >= ask:
        raise ValueError("盘口交叉或锁定，不能作为可用买卖报价")
    return dict(source=BOOK, market_id=market["market_id"], condition_id=condition.lower(),
        token_id=token, book_hash=book_hash, source_timestamp=stamp, received_at=now,
        best_bid=float(bid) if bid is not None else None, best_ask=float(ask) if ask is not None else None,
        spread=float(ask-bid) if bid is not None and ask is not None else None,
        quote_available=bid is not None and ask is not None,
        bids=[dict(price=float(p), size=float(n)) for p, n in sides["bids"][:20]],
        asks=[dict(price=float(p), size=float(n)) for p, n in sides["asks"][:20]],
        bid_levels=len(sides["bids"]), ask_levels=len(sides["asks"]),
        minimum_size=float(minimum), price_tick=float(tick), simulation_ready=False,
        note="盘口来自公开快照，非保证成交；仅展示前20档。" if bid is not None and ask is not None else "单边或空盘口，不能视为双边可用报价")


def resolution_evidence(raw, market, now):
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list) or len(raw["data"]) > 1:
        raise ValueError("官方结算响应无法唯一对应当前市场")
    result = dict(source=RESOLUTION, market_id=market["market_id"], condition_id=market["condition_id"],
        received_at=now, status="NOT_AVAILABLE", settlement_verified=False, onchain_verified=False,
        payouts=None, settlement_asset=None, execution_enabled=False)
    if not raw["data"]:
        return dict(result, reason="官方接口尚无该条件的结算记录；不推断输赢、退款或零兑付")
    row = raw["data"][0]
    if not isinstance(row, dict) or not isinstance(row.get("condition_id"), str) or row["condition_id"].lower() != market["condition_id"]:
        raise ValueError("结算记录的条件 ID 与当前市场不符")
    status = row.get("status")
    if not isinstance(status, str) or not status or len(status) > 80:
        raise ValueError("官方结算状态缺失或无效")
    result.update(status=status, resolved_at=timestamp(row.get("resolved_at")),
        source_updated_at=timestamp(row.get("last_update_timestamp")),
        expected_settlement_time=timestamp(row.get("expected_settlement_time")))
    # Unknown/proposed/disputed states cannot be upgraded using prices or payout-looking fields.
    if status.casefold() != "resolved":
        return dict(result, reason="尚未取得已完成的官方结算状态，不使用现货涨跌或市场价格替代")
    values = row.get("payouts")
    if not isinstance(values, list) or len(values) != len(market["outcomes"]):
        return dict(result, reason="已报告 resolved，但缺少完整结果兑付比例")
    # Official /v2/resolutions schema: per-outcome integer micro-USDC/share.
    # Do not infer a scale from the returned sum or from the spot/collateral asset.
    if any(type(v) is not int or not 0 <= v <= 1_000_000 for v in values) or sum(values) != 1_000_000:
        raise ValueError("官方兑付数值单位或总额无效，应为每份额 micro-USDC 整数")
    payouts = [Decimal(v) / 1_000_000 for v in values]
    resolved = result["resolved_at"]
    if resolved is None or resolved > now:
        return dict(result, reason="官方结算完成时间缺失或在未来，暂不采纳兑付比例")
    result.update(settlement_verified=True, verification="official_api_only",
        payout_source_unit="micro-USDC/share", raw_payouts_micro_usdc=values,
        payouts=[dict(outcome=name["name"], token_id=name["token_id"], payout=float(value))
                 for name, value in zip(market["outcomes"], payouts)],
        reason="已核验官方接口的条件、完成状态、时间和兑付比例；尚未执行链上核对或资金兑付")
    return result


class EventDetails:
    def __init__(self, fetch=None, clock=time.time, monotonic=time.monotonic):
        self.fetch, self.clock, self.monotonic = fetch or public_get, clock, monotonic
        self.closed = Event()
        self.locks = {"quote": Lock(), "resolution": Lock()}
        self.cache = {"quote": OrderedDict(), "resolution": OrderedDict()}

    def _read(self, url, params):
        if self.closed.is_set():
            raise ValueError("事件详情查询已取消")
        result = self.fetch(url, params)
        if self.closed.is_set():
            raise ValueError("事件详情查询已取消")
        return result

    def _market(self, market_id):
        raw = self._read(ENDPOINT + "/" + market_id, {})
        if not isinstance(raw, dict):
            raise ValueError("无法取得唯一的官方市场元数据")
        market = normalize(raw, self.clock())
        if market["market_id"] != market_id:
            raise ValueError("官方市场 ID 与查询不符")
        return market

    def _run(self, lane, key, ttl, callback):
        lock, cache = self.locks[lane], self.cache[lane]
        if not lock.acquire(blocking=False):
            raise ValueError("该类事件详情正在查询，请稍后重试")
        try:
            if self.closed.is_set():
                raise ValueError("事件详情服务已关闭")
            cached = cache.get(key)
            if cached and 0 <= self.monotonic()-cached[0] < ttl:
                value = deepcopy(cached[1])
                stamp = value.get("source_timestamp")
                if lane != "quote" or (stamp is not None and 0 <= self.clock()-stamp < 30):
                    return dict(value, cached=True)
            value = callback()
            if self.closed.is_set():
                raise ValueError("事件详情查询已取消")
            value.update(read_only=True, changes_sessions=False, execution_enabled=False, cached=False)
            cache[key] = (self.monotonic(), deepcopy(value)); cache.move_to_end(key)
            while len(cache) > 64:
                cache.popitem(last=False)
            return value
        finally:
            if self.closed.is_set():
                cache.clear()
            lock.release()
            if self.closed.is_set():
                self.close()

    def quote(self, query):
        def fetch():
            market = self._market(query.market_id)
            if not market["metadata_active"]:
                raise ValueError("市场未确认开放，不能提供当前交易报价")
            outcome = market["outcomes"][query.outcome_index]
            raw = self._read(BOOK, dict(token_id=outcome["token_id"]))
            result = book_snapshot(raw, market, outcome["token_id"], self.clock())
            fee = self._read(FEE, dict(token_id=outcome["token_id"]))
            base = fee.get("base_fee") if isinstance(fee, dict) else None
            if type(base) is not int or not 0 <= base <= 10000:
                raise ValueError("官方基准费率缺失或无效，未假定零手续费")
            if not 0 <= self.clock()-result["source_timestamp"] < 30:
                raise ValueError("费用查询后盘口已过期，请重新读取")
            return dict(result, outcome=outcome["name"], base_fee_bps=base, fee_source=FEE,
                fee_received_at=self.clock(), base_fee_verified=True, fee_model_verified=False,
                fee_note="基准费率不是完整成交费用；尚未核验费用曲线、资产和实际扣费规则")
        return self._run("quote", (query.market_id, query.outcome_index), 3, fetch)

    def resolution(self, query):
        def fetch():
            market = self._market(query.market_id)
            raw = self._read(RESOLUTION, dict(condition=market["condition_id"]))
            return resolution_evidence(raw, market, self.clock())
        return self._run("resolution", query.market_id, 15, fetch)

    def close(self):
        self.closed.set()
        for lane, lock in self.locks.items():
            if lock.acquire(blocking=False):
                try:
                    self.cache[lane].clear()
                finally:
                    lock.release()
