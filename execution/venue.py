"""Exchange transport. Fixed global entities, no proxy or regional failover."""

import time
from decimal import Decimal
import math
import ccxt
from market.feeds import SYMBOLS

D = lambda x: Decimal(str(x))


class Venue:
    def __init__(self, name, product, env, keys=None):
        self.name = name
        self.swap = product == "swap"
        self.env = env
        if (
            name not in ("okx", "binance")
            or product not in ("spot", "swap")
            or env not in ("public", "demo", "live")
        ):
            raise ValueError("交易连接类型无效")
        cls = (
            ccxt.okx
            if name == "okx"
            else ccxt.binanceusdm if self.swap else ccxt.binance
        )
        params = dict(
            timeout=8000,
            enableRateLimit=True,
            options={
                "defaultType": "swap" if self.swap else "spot",
                "fetchCurrencies": False,
                "warnOnFetchOpenOrdersWithoutSymbol": False,
                "fetchMarkets": (
                    {"types": ["linear" if self.swap else "spot"]}
                    if name == "binance"
                    else {"types": ["swap" if self.swap else "spot"]}
                ),
            },
        )
        if keys:
            params.update(
                apiKey=keys["key"],
                secret=keys["secret"],
                password=keys.get("passphrase", ""),
            )
        self.client = cls(params)
        self.client.session.trust_env = False
        if env == "demo":
            if name == "binance":
                self.client.enable_demo_trading(True)
            else:
                self.client.set_sandbox_mode(True)
        self.client.load_markets()

    def pair(self, s):
        return s + "/USDT" + (":USDT" if self.swap else "")

    def market(self, k):
        m = self.client.market(self.pair(k))
        if not m["active"] or (self.swap and not (m["linear"] and m["swap"])):
            raise ValueError("标的不在可交易范围")
        return m

    def bars(self):
        result = {}
        for k in SYMBOLS:
            pair = self.pair(k)
            if pair not in self.client.markets:
                continue
            rows = self.client.fetch_ohlcv(pair, "1m", limit=245)
            result[k] = [
                (int(t) // 1000 + 60, o, h, l, c, v * c)
                for t, o, h, l, c, v in rows
                if t / 1000 + 60 <= time.time()
            ]
        return result

    def balance(self):
        b = self.client.fetch_balance()
        return float(b.get("free", {}).get("USDT") or 0), b.get("free", {})

    def audit(self, s):
        if not self.swap:
            return self.audit_spot(s)
        free, balances = self.balance()
        if not s.get("account") and free < s["config"]["capital"]:
            raise ValueError("账户可用 USDT 低于本次资金预算")
        if self.swap:
            pairs = [
                self.pair(k) for k in SYMBOLS if self.pair(k) in self.client.markets
            ]
            positions = self.client.fetch_positions(pairs)
            observed = {}
            for p in positions:
                contracts = float(p.get("contracts") or 0)
                if contracts:
                    if p["side"] != "long" or p.get("hedged"):
                        raise ValueError("策略要求单向持仓，检测到其他方向或双向模式")
                    observed[p["symbol"]] = contracts * float(
                        self.client.market(p["symbol"])["contractSize"]
                    )
            for k in SYMBOLS:
                expected = s["positions"].get(k, {}).get("qty", 0)
                if abs(observed.get(self.pair(k), 0) - expected) > max(
                    1e-10, expected * 1e-7
                ):
                    raise ValueError("合约仓位不一致，已暂停策略执行")
        elif any(
            float(balances.get(k) or 0) + 1e-10 < p["qty"]
            for k, p in s["positions"].items()
        ):
            raise ValueError("交易所可用币数不足，持仓需核对")
        return dict(free_usdt=free, checked=int(time.time()))

    def audit_spot(self, s):
        """Only accept a dedicated spot allocation that can be exactly reconciled."""
        balances = self.client.fetch_balance()
        free, used, total = (balances.get(k) for k in ("free", "used", "total"))
        if not all(isinstance(v, dict) for v in (free, used, total)) or "USDT" not in free:
            raise ValueError("账户未返回可用、冻结及总额明细")
        expected = {"USDT": s["cash"], **{k: p["qty"] for k, p in s["positions"].items()}}
        for asset in set(total) | set(free) | set(used) | set(expected):
            a, locked, balance = (D(bucket.get(asset) or 0) for bucket in (free, used, total))
            want = D(expected.get(asset, 0))
            if (not all(n.is_finite() and n >= 0 for n in (a, locked, balance, want))
                    or locked or abs(balance - a) > D("1e-12")
                    or abs(a - want) > max(D("1e-12"), want * D("1e-10"))):
                raise ValueError("专用现货账户与策略账本不一致，请核对冻结资金、外部交易和余额")
        if self.client.fetch_open_orders():
            raise ValueError("专用账户有未结委托，请先核对")
        return {"free_usdt": float(free["USDT"]), "checked": int(time.time()),
                "dedicated_balance_match": True}

    def permission_check(self):
        if self.swap:
            raise ValueError("新版真实资金验收仅开放现货。旧合约记录保留供查单核对")
        if self.name == "okx":
            response = self.client.privateGetAccountConfig()
            if response.get("code") != "0" or len(response.get("data", [])) != 1:
                raise ValueError("OKX 账户权限回报不可核验")
            info = response["data"][0]
            permissions = set(str(info.get("perm", "")).split(","))
            if permissions != {"read_only", "trade"} or not info.get("uid"):
                raise ValueError("OKX 密钥需可核验的只读与交易权限，并关闭提现")
            uid = str(info["uid"])
        else:
            info = self.client.privateGetAccount()
            if info.get("canTrade") is not True or "SPOT" not in info.get("permissions", []) or not info.get("uid"):
                raise ValueError("Binance 现货账户身份或交易权限无法验证")
            uid = str(info["uid"])
            if self.env == "live":
                perm = self.client.sapiGetAccountApiRestrictions()
                allowed = {"enableReading", "enableSpotAndMarginTrading"}
                if (not all(perm.get(k) is True for k in allowed)
                        or perm.get("enableWithdrawals") is not False
                        or any(v is True for k, v in perm.items()
                               if k.startswith(("enable", "permits")) and k not in allowed)):
                    raise ValueError("Binance 密钥权限不符合专用现货账户要求")
        from execution.identity import digest
        return {"venue_account_id": digest([self.name, self.env, uid])}

    def algo_inventory(self):
        """Read all pending spot algo types; never adopt external orders as protection."""
        if self.name != "okx" or self.swap:
            raise ValueError("此保护单清单仅支持 OKX 现货")
        result, seen = [], set()
        for kind in ("conditional", "oco", "trigger", "move_order_stop", "iceberg", "twap", "smart_iceberg"):
            cursor = None
            for _ in range(20):
                params = {"instType": "SPOT", "ordType": kind, "limit": "100"}
                if cursor:
                    params["after"] = cursor
                response = self.client.privateGetTradeOrdersAlgoPending(params)
                rows = response.get("data")
                if response.get("code") != "0" or not isinstance(rows, list) or len(rows) > 100:
                    raise ValueError("交易所条件单清单读取失败，无法确认保护状态")
                for row in rows:
                    algo = str(row.get("algoId") or "")
                    if not algo or algo in seen or row.get("instType") != "SPOT":
                        raise ValueError("交易所条件单分页重复或身份不完整")
                    seen.add(algo)
                    result.append({k: row.get(k, "") for k in (
                        "algoId", "instId", "instType", "ordType", "state", "side", "sz",
                        "slTriggerPx", "slOrdPx", "tdMode")})
                if len(rows) < 100:
                    break
                cursor = str(rows[-1]["algoId"])
            else:
                raise ValueError("条件单超过本轮核对上限，清单不完整")
        return result

    def market_check(self):
        self.client.load_markets(True)
        verified = []
        for k in SYMBOLS:
            if self.pair(k) not in self.client.markets:
                continue
            market = self.client.market(self.pair(k))
            if market.get("active") is not True or market.get("spot") is not True:
                continue
            verified.append(self.spot_rules(k, market))
        if not verified:
            raise ValueError("无可核验规则的现货交易对")
        return {"market_rules": "verified", "pairs": verified}

    def lookup_stop(self, client_id):
        """Read one original algo by its client ID, including after a timeout.

        No pending-list absence inference, ownership adoption or write operation.
        Full position/parameter checks belong to the hosted lifecycle ledger.
        """
        if self.name != "okx" or self.swap:
            raise ValueError("当前仅实现 OKX 现货保护单只读查询")
        if not isinstance(client_id, str) or not client_id.isascii() or not client_id.isalnum() or len(client_id) > 32:
            raise ValueError("保护单客户端标识无效")
        response = self.client.privateGetTradeOrderAlgo({"algoClOrdId": client_id})
        rows = response.get("data") if isinstance(response, dict) else None
        if (not isinstance(response, dict) or response.get("code") != "0"
                or not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
                or rows[0].get("algoClOrdId") != client_id
                or not isinstance(rows[0].get("algoId"), str) or not rows[0]["algoId"].strip()):
            raise ValueError("保护单查询结果未确认，禁止根据空清单重新提交")
        return {k: rows[0].get(k) for k in (
            "algoId", "algoClOrdId", "instId", "instType", "tdMode", "side", "ordType", "state",
            "sz", "slTriggerPx", "slOrdPx", "slTriggerPxType", "tpTriggerPx", "tgtCcy",
            "ordIdList", "actualSz", "uTime", "failCode")}

    def spot_rules(self, k, market):
        """Shared checks for admission and the actual order's refreshed market."""
        if market.get("active") is not True or market.get("spot") is not True:
            raise ValueError(f"{self.pair(k)} 不是可交易的现货交易对")
        mode = self.client.precisionMode
        precision = market.get("precision") or {}
        valid = lambda n: (isinstance(n, (int, float)) and not isinstance(n, bool)
                           and math.isfinite(n))
        limits = market.get("limits")
        if not isinstance(limits, dict):
            raise ValueError(f"{self.pair(k)} 限额规则不完整，无法完成规则验收")
        for field, name in (("amount", "数量"), ("price", "价格"), ("cost", "金额")):
            rule = limits.get(field, {})
            if not isinstance(rule, dict):
                raise ValueError(f"{self.pair(k)} {name}限额格式无效，无法完成规则验收")
            low, high = rule.get("min"), rule.get("max")
            if ((low is not None and (not valid(low) or low < 0)) or
                    (high is not None and (not valid(high) or high <= 0))):
                raise ValueError(f"{self.pair(k)} {name}限额数值无效，无法完成规则验收")
            if low is not None and high is not None and low > high:
                raise ValueError(f"{self.pair(k)} {name}上下限矛盾，无法完成规则验收")
        minimum = limits.get("amount", {}).get("min")
        if not valid(minimum) or minimum <= 0:
            raise ValueError(f"{self.pair(k)} 缺少有效的最小下单数量，无法完成规则验收")
        for field in ("amount", "price"):
            value = precision.get(field)
            if (not valid(value) or
                    not ((mode == ccxt.TICK_SIZE and value > 0) or
                         (mode == ccxt.DECIMAL_PLACES and value >= 0 and value == int(value)))):
                raise ValueError(f"{self.pair(k)} 数量或价格精度不完整，无法完成规则验收")
        cost = limits.get("cost", {}).get("min")
        return dict(symbol=self.pair(k), min_quantity=minimum,
                    quantity_precision=precision["amount"], price_precision=precision["price"],
                    precision_mode=mode, min_notional=cost)

    def preflight(self, state):
        """Read-only admission; never send a test order or change permissions."""
        account_id = self.permission_check()["venue_account_id"]
        if self.name == "okx" and self.algo_inventory():
            raise ValueError("发现未核对的交易所条件单，禁止与本地止损同时自动交易")
        self.market_check()
        result = self.audit(state)
        if state.get("venue_account_id", account_id) != account_id:
            raise ValueError("当前交易所账户与原授权账户不符")
        return {**result, "venue_account_id": account_id, "protection": "local_only"}

    def quote(self, k):
        pair = self.pair(k)
        book = self.client.fetch_order_book(pair, 5)
        timestamp = book.get("timestamp")
        if timestamp is None:
            # Some REST depth messages have no exchange timestamp.
            ticker = self.client.fetch_ticker(pair)
            bid, ask, timestamp = ticker.get("bid"), ticker.get("ask"), ticker.get("timestamp")
        else:
            bid, ask = book["bids"][0][0], book["asks"][0][0]
        if not timestamp or not 0 <= time.time() - timestamp / 1000 <= 10:
            raise ValueError("保护行情缺失、过期或本机时钟不一致")
        if not bid or not ask or not math.isfinite(ask) or not 0 < bid <= ask:
            raise ValueError("缺少可核验的买卖盘口")
        return bid, ask, timestamp / 1000

    def prepare(self, k, side, amount, holding, reference, leverage):
        pair = self.pair(k)
        if not self.swap:
            # Refresh in the order lane, never on every scan or market tick.
            try:
                self.client.load_markets(True)
            except Exception as err:
                # Preserve regional refusal handling; never show raw responses or keys.
                if "451" in str(err) or "restricted location" in str(err).lower():
                    raise
                detail = ("交易所请求频率受限，请稍后重新核验"
                          if isinstance(err, ccxt.RateLimitExceeded)
                          else "请检查交易所连接后重新核验")
                raise ValueError("交易规则刷新失败，已阻止下单；" + detail) from None
        m = self.market(k)
        if not self.swap:
            self.spot_rules(k, m)
        bid, ask, asof = self.quote(k)
        if not 0 < bid <= ask or ask / bid - 1 > 0.003:
            raise ValueError("盘口价差超过 0.3%")
        price = ask * 1.001 if side == "BUY" else bid * 0.999
        if abs(price / reference - 1) > 0.01:
            raise ValueError("报价偏离策略参考价超过 1%")
        free, balances = self.balance()
        contract = float(m.get("contractSize") or 1)
        if self.client.fetch_open_orders(pair):
            raise ValueError("交易对已有未结委托，禁止重复暴露")
        qty = amount / price if side == "BUY" else holding
        if self.swap:
            positions = self.client.fetch_positions([pair])
            active = [p for p in positions if float(p.get("contracts") or 0) > 0]
            if any(p["side"] != "long" for p in active) or abs(
                sum(float(p["contracts"]) * contract for p in active) - holding
            ) > max(1e-10, holding * 1e-7):
                raise ValueError("交易所合约仓位与本策略持仓不一致")
            if side == "BUY":
                if free < amount / leverage + amount * 0.005:
                    raise ValueError("可用保证金不足")
                if self.name == "binance":
                    raw = self.client.fapiPrivateGetSymbolConfig({"symbol": m["id"]})[0]
                    if (
                        raw["marginType"].lower() != "isolated"
                        or int(raw["leverage"]) != leverage
                    ):
                        raise ValueError("请先在交易所设置匹配的逐仓杠杆")
                else:
                    raw = self.client.privateGetAccountLeverageInfo(
                        {"instId": m["id"], "mgnMode": "isolated"}
                    )["data"]
                    if not raw or any(int(float(p["lever"])) != leverage for p in raw):
                        raise ValueError("逐仓杠杆与策略配置不一致")
        elif side == "BUY" and free < amount * 1.005:
            raise ValueError("USDT 可用余额不足")
        elif side == "SELL" and float(balances.get(k) or 0) + 1e-12 < holding:
            raise ValueError("交易所现货余额不足")
        qty = float(self.client.amount_to_precision(pair, qty / contract))
        price = float(self.client.price_to_precision(pair, price))
        limits = m["limits"]
        if not all(math.isfinite(x) and x > 0 for x in (qty, price, contract)) or any(
            (rule.get("min") is not None and val < rule["min"])
            or (rule.get("max") is not None and val > rule["max"])
            for val, rule in [
                (qty, limits.get("amount", {})),
                (price, limits.get("price", {})),
                (qty * contract * price, limits.get("cost", {})),
            ]
        ):
            raise ValueError("订单未通过交易所精度或金额规则")
        return dict(quantity=qty, price=price, contract=contract, quote_time=asof)

    def cancel(self, order):
        # A cancel acknowledgement never constitutes a final receipt.
        return self.client.cancel_order(order["exchange_id"], self.pair(order["symbol"]))

    def submit(self, order, prepared):
        k = order["symbol"]
        side = order["side"].lower()
        params = {"clientOrderId": order["client_id"], "timeInForce": "IOC"}
        if self.name == "okx":
            params["tdMode"] = "isolated" if self.swap else "cash"
        if self.swap and side == "sell":
            params["reduceOnly"] = True
        return self.client.create_order(
            self.pair(k), "limit", side, prepared["quantity"], prepared["price"], params
        )

    def lookup(self, o):
        pair = self.pair(o["symbol"])
        result = self.client.fetch_order(
            o.get("exchange_id") or o["client_id"],
            pair,
            {} if o.get("exchange_id") else {"clientOrderId": o["client_id"]},
        )
        if (
            (result.get("clientOrderId") != o["client_id"] and
             (result.get("info") or {}).get("origClientOrderId") != o["client_id"])
            or result.get("symbol") != pair
            or result.get("side") != o["side"].lower()
            or (o.get("exchange_id") and str(result.get("id")) != str(o["exchange_id"]))
            or (result.get("amount") is not None and
                not math.isclose(float(result["amount"]), o["prepared"]["quantity"], rel_tol=1e-10))
        ):
            raise ValueError("订单编号、标的或方向不匹配，须对账")
        return result

    def executions(self, o, order):
        if self.name == "okx":
            return self.okx_executions(o, order)
        if self.swap and self.name == "binance":
            fills = self.client.fetch_my_trades(
                self.pair(o["symbol"]), params={"orderId": int(order["id"])}
            )
        else:
            fills = self.client.fetch_order_trades(order["id"], self.pair(o["symbol"]))
        return [t for t in fills if str(t.get("order")) == str(order["id"])]

    def okx_executions(self, o, order):
        """Stable bill-ID pagination; never settle from truncated receipts."""
        market = self.market(o["symbol"])
        result, seen, cursor = [], set(), None
        for _ in range(20):
            params = {"instType": "SWAP" if self.swap else "SPOT",
                      "instId": market["id"], "ordId": str(order["id"]), "limit": "100"}
            if cursor:
                params["after"] = cursor
            response = self.client.privateGetTradeFillsHistory(params)
            rows = response.get("data")
            if response.get("code") != "0" or not isinstance(rows, list) or len(rows) > 100:
                raise ValueError("成交分页读取失败，保留未知状态等待核对")
            for row in rows:
                bill = str(row.get("billId") or "")
                if (not bill or bill in seen or str(row.get("ordId")) != str(order["id"])
                        or row.get("instId") != market["id"]
                        or row.get("side") != o["side"].lower()):
                    raise ValueError("成交分页重复、缺少账单标识或原单身份不符")
                seen.add(bill)
                trade = self.client.parse_trade(row, market)
                if not trade.get("id") or (trade.get("fee") or {}).get("cost") is None:
                    raise ValueError("成交缺少可核验的逐笔标识或费用")
                result.append(trade)
            if len(rows) < 100:
                return result
            cursor = str(rows[-1]["billId"])
        raise ValueError("成交超过本轮核对上限，禁止使用不完整明细结算")
