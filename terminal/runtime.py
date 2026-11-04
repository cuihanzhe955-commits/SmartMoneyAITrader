import hashlib
import json
import threading
import time
from functools import lru_cache
from pathlib import Path
from challenge.manager import create, scan, action, finish, snapshot, market_time, protective_exit, decision
from events.store import Store, encode
from execution import live
from execution.venue import Venue
from ai.coordinator import Coordinator, expired
from execution.identity import digest, scope, position_version
from market.feeds import historical, START
from market.imports import parse_csv, window
from ai.provider import Provider
from terminal.settings import Vault, AIConfig
from risk.limits import equity, allowance, finalize

DONE = {"COMPLETED", "STOPPED"}


def protection_ready(s):
    for symbol, position in s["positions"].items():
        watch = s.get("local_watch", {}).get(symbol, {})
        if (watch.get("error") or watch.get("trigger") or watch.get("quantity") != position["qty"]
                or not 0 <= time.time() - watch.get("quote_time", 0) < 20):
            return False
    return True


def safe_error(e):
    if "451" in str(e) or "restricted location" in str(e).lower():
        return "HTTP 451 · 交易所拒绝当前地区的服务请求"
    return (
        str(e)[:220]
        if type(e) is ValueError
        else type(e).__name__ + " · 请求未完成，请检查连接或账户配置"
    )


class Runtime:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime_id = digest([str(self.root), time.time_ns()])
        self.db = Store(self.root / "terminal.db")
        self.lock = threading.RLock()
        self.exit = threading.Event()
        self.vault = Vault(self.root / "credentials.dpapi")
        self.clients = {}
        self.ai = Coordinator()
        self.order_mutex = threading.Lock()
        self.health_mutex = threading.Lock()
        self.background = False
        self.threads = []
        with self.db.db:
            self.db.db.execute("BEGIN IMMEDIATE")
            live.setup(self.db)
            self.db.db.execute("""CREATE TABLE IF NOT EXISTS acceptance_reports(
                id TEXT PRIMARY KEY, session_id INTEGER NOT NULL, created_at INTEGER NOT NULL, body TEXT NOT NULL)""")
            self.db.db.execute(
                "CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,name TEXT,start INTEGER,end INTEGER,rows TEXT)"
            )
            self.db.db.execute(
                "CREATE TABLE IF NOT EXISTS preferences(id TEXT PRIMARY KEY,body TEXT)"
            )

    def start_worker(self):
        with self.lock, self.db.db:
            for cid, order in live.unresolved(self.db):
                if order["stage"] == "QUEUED":
                    live.save(self.db, order, "CANCELLED")
                else:
                    order["retry"] = 0
                    live.save(self.db, order, order["stage"])
            state = self.db.load()
            if state and state["config"].get("execution", "paper") != "paper" and state["lifecycle_status"] not in DONE | {"CREATED"}:
                state.update(lifecycle_status="PAUSED", local_armed=False, admitted=False, needs_check=True,
                             recovery_required=True, latest="重启后先查原单、核对账户。核验后可手动恢复")
                self.db.save(state)
        self.background = True
        for name, callback, period in (("market", self.tick, .04), ("orders", self.order_tick, .25),
                                       ("protection", self.protection_tick, 2)):
            thread = threading.Thread(target=self.loop, args=(name, callback, period),
                                      name="smart-money-" + name, daemon=True)
            self.threads.append(thread)
            thread.start()
        self.thread = self.threads[0]

    def shutdown(self):
        self.exit.set()
        with self.lock:
            self.ai.worker.invalidate()
        for thread in self.threads:
            thread.join()

    def account_key(self, c):
        return c["exchange"] + "/" + c["execution"]

    def account_ref(self, c):
        if c["execution"] == "paper":
            return "paper"
        keys = self.vault.values.get(self.account_key(c)) or {}
        if not keys.get("key"):
            raise ValueError("原授权账户的密钥不可用")
        return digest([self.account_key(c), keys["key"]])

    def check_binding(self, s):
        if self.account_ref(s["config"]) != s.get("account_ref"):
            raise ValueError("原账户绑定无法核验，保留订单并暂停，请人工核对")

    def invalidate_ai(self, s, reason):
        self.ai.worker.invalidate()
        s.pop("ai_last_advice", None)
        if s.get("ai_requested_snapshot"):
            self.db.record("system_events", s, "AI_SKIP", reason)

    def venue(self, c):
        key = (
            threading.current_thread().name,
            c["exchange"],
            c["product"],
            c["execution"] if c["execution"] != "paper" else "public",
        )
        if key not in self.clients:
            keys = (
                self.vault.values.get(self.account_key(c))
                if key[3] != "public"
                else None
            )
            if key[3] != "public" and not keys:
                raise ValueError("请先保存对应环境的交易所凭据")
            self.clients[key] = Venue(*key[1:], keys)
        return self.clients[key]

    def new(self, body):
        c = body.settings()
        if live.unresolved(self.db):
            raise ValueError("先核对原会话未完订单，再创建新会话或切换平台")
        if c["execution"] == "live" and c["product"] != "spot":
            raise ValueError("新实盘会话仅支持现货")
        if c["execution"] != "paper":
            for row in self.db.db.execute("SELECT state FROM challenges"):
                old = json.loads(row[0])
                if (old.get("positions") or old.get("needs_check")) and old["config"].get("execution") == c["execution"]:
                    raise ValueError(f"会话 #{old['id']} 仍有持仓或待核对余额，须先完成交接")
        if c["paper_rules"] == "venue" and c["execution"] == "paper":
            if c["product"] != "spot" or c["exchange"] != "okx":
                raise ValueError("离线交易规则快照仅覆盖 OKX 现货")
            bundle = json.loads(
                (
                    Path(__file__).resolve().parents[1] / "data/okx-spot-rules.json"
                ).read_text()
            )
            c.update(precision_rules=bundle["markets"], rules_as_of=bundle["as_of"])
        if c["execution"] != "paper" and self.account_key(c) not in self.vault.values:
            raise ValueError("请在设置中配置所选交易所及环境")
        if c["engine"] == "ai" and not self.vault.values.get("ai_key"):
            raise ValueError("请先配置 AI 服务")
        s = create(self.db, {}, validated=c)
        s["revision"] = 0
        s["account_ref"] = self.account_ref(c)
        if c["source"] == "csv":
            r = self.db.db.execute(
                "SELECT start,end FROM datasets WHERE id=?", (c["dataset"],)
            ).fetchone()
            if not r:
                raise ValueError("请选择已导入的数据集")
            if c["profile"] == "challenge" and r[1] - r[0] < 86400:
                raise ValueError("挑战需要完整 24 小时行情和预热数据")
            s.update(
                start=r[0], t=r[0], next_scan=r[0], deadline=min(r[1], r[0] + 86400)
            )
        self.db.save(s)
        return s

    def add_csv(self, name, text):
        rows, start, end = parse_csv(text)
        key = hashlib.sha256(text.encode()).hexdigest()[:20]
        self.db.db.execute(
            "INSERT OR IGNORE INTO datasets VALUES(?,?,?,?,?)",
            (key, name, start, end, encode(rows)),
        )
        return key

    @lru_cache(maxsize=2)
    def dataset(self, key):
        return json.loads(
            self.db.db.execute(
                "SELECT rows FROM datasets WHERE id=?", (key,)
            ).fetchone()[0]
        )

    def command(self, cid, cmd, confirm=""):
        s = self.db.load()
        if not s or s["id"] != cid:
            raise ValueError("当前会话已变更")
        c = s["config"]
        p = live.pending(self.db, cid)
        if (
            cmd in ("start", "resume", "use_rules")
            and c["execution"] == "live"
            and confirm != "启用实盘"
        ):
            raise ValueError("请输入「启用实盘」")
        if cmd == "resume" and p:
            raise ValueError("交易所订单待核对")
        if cmd == "reconcile":
            if not p or p["stage"] == "QUEUED":
                raise ValueError("没有待查交易所回报")
            if not p.get("account_ref"):
                if confirm != "核对原账户":
                    raise ValueError("请核对原交易所、账户及客户端单号后确认绑定")
                p["verify_legacy_key"] = self.account_ref(c)
            p["retry"] = 0
            live.save(self.db, p, p["stage"])
            return s
        if cmd == "use_rules":
            if c["engine"] != "ai" or c["profile"] == "challenge" or s["lifecycle_status"] in DONE:
                raise ValueError("当前会话不支持此操作")
            if p:
                raise ValueError("请先完成在途委托核对")
            from execution.paper_queue import cancel
            for symbol, item in list(s.get("paper_pending", {}).items()):
                if item.get("proposal"):
                    cancel(self.db, s, symbol, "用户切换决策引擎")
            self.invalidate_ai(s, "用户切回规则引擎")
            s.update(engine_override="rules", ai_status="手动切回规则", ai_manual=False,
                     revision=s.get("revision", 0) + 1)
            self.db.record("system_events", s, "ENGINE", "用户在原预算内切回规则引擎")
            self.db.save(s)
            return s
        if cmd in ("end", "stop") and p and p["stage"] != "QUEUED":
            p.update(cancel_requested=True, retry=0)
            live.save(self.db, p, p["stage"])
            s["ending"] = cmd
            s["lifecycle_status"] = "PAUSED"
            s["latest"] = "已禁止新订单，等待在途订单终态"
        elif cmd == "step":
            if (
                c["source"] == "public"
                or s["lifecycle_status"] != "PAUSED"
                or s["breaker"]
                or c["engine"] != "rules"
            ):
                raise ValueError("单步仅用于已暂停的历史规则回放")
            t = min(s["deadline"], s["t"] + 60)
            scan(self.db, s, t, self.feed(c, t), manage=t < s["deadline"])
            if t == s["deadline"]:
                finish(self.db, s)
            else:
                s["lifecycle_status"] = "PAUSED"
                s["anchor"] = time.time() - (t - s["start"]) / c["speed"]
        else:
            if p and p["stage"] == "QUEUED" and cmd in ("end", "stop", "pause"):
                live.save(self.db, p, "CANCELLED")
            if cmd == "resume" and c["source"] != "public" and c["profile"] == "normal":
                s["anchor"] = time.time() - (s["t"] - s["start"]) / c["speed"]
            action(self.db, s, cmd)
        if cmd in ("pause", "end", "stop", "start", "resume"):
            self.invalidate_ai(s, "会话状态已变更")
        if cmd in ("start", "resume") and c["execution"] != "paper":
            self.check_binding(s)
            s.update(admitted=False, recovery_required=True, needs_check=True,
                     latest="等待账户、规则、保护与账本预检")
        if cmd in ("stop", "end") and s["positions"] and c["execution"] != "paper":
            s["latest"] = "交易所持仓仍在。本地止损随会话结束而停止，请核对或接管仓位"
            self.db.record("system_events", s, "PROTECTION_OFF", s["latest"])
        s["revision"] = s.get("revision", 0) + 1
        self.db.save(s)
        return s

    def feed(self, c, t):
        if c["source"] == "csv":
            return window(self.dataset(c["dataset"]), t)
        if c["source"] == "history":
            return historical(t)
        return self.venue(c).bars()

    def loop(self, lane, step, period):
        while not self.exit.wait(period):
            try:
                step()
            except Exception as err:
                with self.lock, self.db.db:
                    state = self.db.load()
                    if state and state["lifecycle_status"] not in DONE:
                        msg = safe_error(err)
                        if state.get("latest") != msg:
                            self.db.record("system_events", state, "ERROR", lane + " · " + msg)
                        state.update(lifecycle_status="ERROR", admitted=False, latest=msg,
                                     recovery_required=True, needs_check=state["config"].get("execution")!="paper")
                        self.db.save(state)
                self.exit.wait(1)

    def admit(self, state):
        self.check_binding(state)
        proof = self.venue(state["config"]).preflight(state)
        if (not isinstance(proof, dict) or not proof.get("venue_account_id")
                or proof.get("dedicated_balance_match") is not True
                or not 0 <= time.time() - proof["checked"] < 30):
            raise ValueError("账户预检缺少可核验的余额、身份或时效")
        with self.lock, self.db.db:
            current = self.db.load()
            if (current["id"] != state["id"] or current.get("revision") != state.get("revision")
                    or position_version(current) != position_version(state)):
                return False
            if self.db.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("账本完整性检查失败")
            if current.get("venue_account_id", proof["venue_account_id"]) != proof["venue_account_id"]:
                raise ValueError("交易所账户身份变更")
            current.update(venue_account_id=proof["venue_account_id"], account=proof,
                           admitted=current["lifecycle_status"] not in DONE, needs_check=False, recovery_required=False)
            if current["lifecycle_status"] in ("INITIALIZING", "RUNNING"):
                current["local_armed"] = True
            self.db.record("system_events", current, "RECONCILED", "账户、规则和账本已核验；仅本地止损")
            self.db.save(current)
        return True

    def order_tick(self):
        with self.lock:
            for cid, order in live.unresolved(self.db):
                if time.time() >= order.get("retry", 0):
                    state = self.db.load(cid)
                    break
            else:
                state, order = self.db.load(), None
        if order:
            self.dispatch(state, order)
        elif state and state["lifecycle_status"] in DONE and state.get("needs_check") and time.time() >= state.get("audit_retry", 0):
            try:
                self.admit(state)
            except Exception as err:
                with self.lock, self.db.db:
                    cur = self.db.load(state["id"])
                    msg = "会话结束后余额待核对 · " + safe_error(err)
                    if cur.get("latest") != msg:
                        self.db.record("system_events", cur, "RECONCILE", msg)
                    cur.update(latest=msg, audit_retry=time.time() + 30)
                    self.db.save(cur)

    def protection_tick(self):
        # A dedicated book/position lane. No AI, archive scans, or pending order
        # lookups are awaited here. Only a verified held quantity can be sold.
        with self.lock:
            state = self.db.load()
            if (not state or not state["positions"] or state.get("ending")
                    or state["config"].get("execution", "paper") == "paper"
                    or state["lifecycle_status"] in DONE | {"CREATED"}
                    or time.time() >= state["deadline"]):
                return
            holdings = list(state["positions"])
        self.check_binding(state)
        venue = self.venue(state["config"])
        for symbol in holdings:
            if self.exit.is_set():
                return
            try:
                price, _, quote_time = venue.quote(symbol)
                error = ""
            except Exception as err:
                error = safe_error(err)
            with self.lock, self.db.db:
                cur = self.db.load()
                if (cur["id"] != state["id"] or cur["lifecycle_status"] in DONE
                        or cur.get("ending") or cur.get("revision") != state.get("revision")):
                    return
                position = cur["positions"].get(symbol)
                if position is None:
                    continue
                watches = cur.setdefault("local_watch", {})
                if error:
                    if watches.get(symbol, {}).get("error") != error:
                        self.db.record("system_events", cur, "PROTECTION_ERROR", error, symbol)
                    watches[symbol] = {"error": error, "checked": time.time()}
                    self.db.save(cur)
                    continue
                position["high"] = max(price, position["high"])
                reason = protective_exit(position, price, cur["config"])
                watches[symbol] = {"checked": time.time(), "quote_time": quote_time, "bid": price,
                                   "quantity": position["qty"], "trigger": reason}
                if reason:
                    order = live.pending(self.db, cur["id"])
                    if order and order["side"] == "BUY" and order["symbol"] == symbol:
                        if order["stage"] == "QUEUED":
                            live.save(self.db, order, "CANCELLED")
                        else:
                            order["cancel_requested"] = True
                            live.save(self.db, order, order["stage"])
                    if (not live.unresolved(self.db) and cur.get("admitted") and cur.get("local_armed")
                            and not cur.get("recovery_required") and not self.exit.is_set()):
                        metrics = {"price": price, "time": int(quote_time), "score": 0, "protective": True}
                        decision(self.db, cur, symbol, metrics, "SELL", reason)
                        live.enqueue(self.db, cur, symbol, "SELL", metrics, 0, reason)
                    else:
                        watches[symbol]["waiting"] = "等待原单或账户核对"
                self.db.save(cur)

    def tick(self):
        if not self.background:
            with self.lock:
                pending = bool(live.unresolved(self.db))
            if pending:
                return self.order_tick()
        with self.lock:
            s = self.db.load()
            if not s or s["lifecycle_status"] in DONE | {"CREATED"}:
                return
            c = s["config"]
            now = market_time(s)
            remote = c["execution"] != "paper"
            has_pending = bool(live.unresolved(self.db))
            paused = s["lifecycle_status"] in ("PAUSED", "ERROR")
            if paused and not (not remote and s["breaker"] and s["positions"]):
                if remote and s.get("needs_check") and not has_pending and time.time() >= s.get("audit_retry", 0):
                    pass  # reconcile even a paused/restarted session without opening a trade
                elif now >= s["deadline"] and not has_pending and (c["profile"] == "challenge" or c["source"] == "public"):
                    with self.db.db:
                        s["t"] = now
                        finish(self.db, s)
                    return
                else:
                    return
            due = (s.get("next_scan") or now) <= now or now >= s["deadline"]
            ai_active = c["profile"] != "challenge" and s.get("engine_override", c["engine"]) == "ai"
            early = not due and ai_active and self.ai.worker.ready()
            if not due and not early and not s.get("needs_check"):
                return
            t = now if c["source"] == "public" else min(s.get("next_scan") or now, s["deadline"])
            if early:
                t = now
            identity = (s["id"], s.get("revision", 0), position_version(s))
        try:
            if remote and (s.get("needs_check") or not s.get("admitted")):
                if has_pending or not self.admit(s) or paused:
                    return
            bars = self.feed(c, t)
            account = None
            if remote and not has_pending:
                self.check_binding(s)
                account = self.venue(c).audit(s)
            reason = ""
        except Exception as err:
            reason, bars, account = safe_error(err), {}, None
        with self.lock, self.db.db:
            cur = self.db.load()
            if (self.exit.is_set() or identity != (cur["id"], cur.get("revision", 0), position_version(cur))
                    or cur["lifecycle_status"] in DONE):
                return
            if c["source"] == "public":
                t = market_time(cur)
            if reason and remote:
                if cur.get("latest") != reason:
                    self.db.record("system_events", cur, "RECONCILE", reason)
                cur.update(latest=reason, lifecycle_status="PAUSED", admitted=False, needs_check=True,
                           recovery_required=True, feed_valid=False, audit_retry=time.time() + 15)
                self.db.save(cur)
                return
            if account:
                cur["account"] = account
            if remote and cur["lifecycle_status"] in ("PAUSED", "ERROR"):
                return
            has_pending = bool(live.unresolved(self.db))
            previous_cursor = cur.get("next_scan")
            advice, block = None, False
            if bars:
                cur["market_version"] = digest([scope(cur), bars])
            if (c["profile"] != "challenge" and cur.get("engine_override", c["engine"]) == "ai"
                    and bars and t < cur["deadline"] and not has_pending and not cur["breaker"]):
                advice, block = self.ai.decide(self.db, cur, bars, t, self.vault)
            if remote:
                block |= not protection_ready(cur)
            scan(self.db, cur, t, bars, manage=t < cur["deadline"],
                 advice=advice, block_entries=block, order_pending=has_pending)
            if reason:
                cur["latest"] = reason
                self.db.record("system_events", cur, "ERROR", reason)
                if "HTTP 451" in reason:
                    cur.update(lifecycle_status="PAUSED", next_scan=None)
            if t >= cur["deadline"]:
                if has_pending:
                    cur.update(ending="end", lifecycle_status="PAUSED", latest="到期待交易所终态")
                else:
                    finish(self.db, cur)
            elif early:
                cur["next_scan"] = previous_cursor
            elif c["source"] != "public":
                cur["next_scan"] = min(t + max(60, c["interval"]), cur["deadline"])
            self.db.save(cur)

    def dispatch(self, state, order):
        if not self.order_mutex.acquire(blocking=False):
            return
        try:
            with self.lock:
                current = live.pending(self.db, state["id"])
                if not current or current["client_id"] != order["client_id"]:
                    return
                state, order = self.db.load(state["id"]), current
            try:
                if order.get("account_ref"):
                    self.check_binding(state)
                    if (order["account_ref"] != state.get("account_ref")
                            or (order.get("exchange"), order.get("environment"), order.get("product"))
                            != tuple(state["config"][k] for k in ("exchange", "execution", "product"))):
                        raise ValueError("订单与当前账户或产品不一致")
                elif order["stage"] != "QUEUED" and order.get("verify_legacy_key") != self.account_ref(state["config"]):
                    raise ValueError("旧未决订单缺少账户绑定，需人工核对原账户")
                venue = self.venue(state["config"])
                if order["stage"] == "QUEUED":
                    self.send_intent(venue, state, order)
                else:
                    self.reconcile_order(venue, state, order)
            except Exception as err:
                self.order_error(state["id"], order, err)
        finally:
            self.order_mutex.release()

    def valid_intent(self, state, o):
        self.check_binding(state)
        if o.get("revision") != state.get("revision", 0):
            raise ValueError("订单所属会话版本已变更")
        if o.get("config_version") != digest(state["config"]) or o.get("portfolio_version") != position_version(state):
            raise ValueError("策略版本、持仓或余额已变更")
        if (not o.get("protective") and state.get("market_version")
                and o["snapshot_id"] != state["market_version"]):
            raise ValueError("订单的市场快照已被新行情替代")
        if not 0 <= time.time() - o["bar"] < (10 if o.get("protective") else 120):
            raise ValueError("提交前行情已过期")
        if state["config"]["execution"] == "live" and state["config"]["product"] != "spot":
            raise ValueError("仅允许提交现货实盘委托")
        if state.get("ending") or time.time() >= state["deadline"]:
            raise ValueError("会话结束或订单已过有效时间")
        protective = o.get("protective") and o["side"] == "SELL" and o["symbol"] in state["positions"]
        if state["lifecycle_status"] != "RUNNING" and not (protective and state.get("local_armed")):
            raise ValueError("当前运行状态禁止提交")
        if state["breaker"] and not protective:
            raise ValueError("风控熔断已禁止新增敞口")
        if o["side"] == "BUY" and not protection_ready(state):
            raise ValueError("已有仓位的本地止损监控尚未核验或正在退出")
        stamp = o.get("proposal")
        if stamp:
            cfg = AIConfig(**self.vault.values.get("ai_config", {}))
            signature = digest([cfg.model_dump(), self.vault.values.get("ai_key", "")])
            reason = expired(stamp, state, int(time.time()), same_snapshot=True)
            if signature != stamp["provider"] or state.get("engine_override") == "rules" or reason:
                raise ValueError(reason or "AI 模型或引擎已切换")

    def send_intent(self, venue, s, o):
        db, c = self.db, s["config"]
        self.valid_intent(s, o)
        if not s.get("admitted") or s.get("recovery_required"):
            if not self.admit(s):
                raise ValueError("核验期间账户或会话变化")
        # Recheck the exact isolated funds again before transmitting.
        account = venue.audit(s)
        if c["product"] == "spot" and (not isinstance(account, dict)
                                       or account.get("dedicated_balance_match") is not True):
            raise ValueError("账户余额与策略持仓未核对")
        if o["side"] == "BUY":
            permitted, why, caps = allowance(s, c, {"slip": max(o.get("slippage_budget", .001), .001)})
            amount = min(o["amount"], permitted)
            if amount and amount < permitted:
                why = "限制原因：原委托金额"
            if amount < c.get("strict_min", 1):
                amount, why = 0, "执行前风险或最小金额检查拒绝 · " + why
            nav = caps["calculation"]["nav"]
            finalize(caps, amount, why, {"name": "原委托金额", "amount": o["amount"],
                                         "pct": 100 * o["amount"] / nav if nav else 0})
            o["calculation"] = caps["calculation"]
            with self.lock, db.db:
                db.record("risk_checks", s, "APPROVED" if amount else "REJECT", why, o["symbol"], caps)
            if not amount:
                raise ValueError(why)
            o["amount"] = amount
        prep = venue.prepare(o["symbol"], o["side"], o["amount"], s["positions"].get(o["symbol"], {}).get("qty", 0),
                             o["reference"], c["leverage"])
        if o["side"] == "BUY":
            nominal = prep["quantity"] * prep["contract"] * prep["price"]
            if not c.get("strict_min", 1) <= nominal <= o["amount"] + max(1e-12, o["amount"] * 1e-10):
                raise ValueError("精度处理后的订单金额超出可执行范围")
            caps["calculation"].update(quantity=prep["quantity"]*prep["contract"], price=prep["price"],
                                       precision_status="通过执行器实时规则检查")
            finalize(caps, nominal, "限制原因：交易所数量或价格精度" if nominal < o["amount"] else why)
        with self.lock, db.db:
            current = db.load(s["id"])
            persisted = live.pending(db, s["id"])
            if self.exit.is_set() or not persisted or persisted["client_id"] != o["client_id"] or persisted["stage"] != "QUEUED":
                return
            self.valid_intent(current, o)
            if position_version(current) != position_version(s) or not current.get("admitted"):
                raise ValueError("发送前账本或授权状态已变更")
            if not 0 <= time.time() - prep.get("quote_time", 0) <= 10:
                raise ValueError("执行盘口时间未核验或已过期")
            o.update(prepared=prep, sending_at=time.time())
            live.save(db, o, "SENDING")
            db.record("system_events", current, "SENDING", "提交前已持久化订单意图", o["symbol"],
                      {"client_id": o["client_id"], "decision_id": o["decision_id"],
                       "calculation": o.get("calculation")})
        response = venue.submit(o, prep)
        if not response.get("id"):
            raise ValueError("提交回报缺少交易所订单编号")
        with self.lock, db.db:
            stored = live.pending(db, s["id"])
            stored["exchange_id"] = str(response["id"])
            live.save(db, stored, "SUBMITTED")

    def reconcile_order(self, venue, state, o):
        db = self.db
        order = venue.lookup(o)
        trades = venue.executions(o, order) if live.number(order.get("filled")) > 0 else []
        cancel = False
        with self.lock, db.db:
            cur = db.load(state["id"])
            o = live.pending(db, state["id"])
            if not o.get("account_ref"):
                c = cur["config"]
                ref = self.account_ref(c)
                if (o.get("verify_legacy_key") != ref or order.get("clientOrderId") != o["client_id"]
                        or order.get("symbol") != venue.pair(o["symbol"])
                        or order.get("side") != o["side"].lower()
                        or live.number(order.get("amount")) != live.number(o["prepared"]["quantity"])):
                    raise ValueError("原账户、委托数量或客户端标识不能核实")
                o.update(account_ref=ref, exchange=c["exchange"], product=c["product"], environment=c["execution"])
                cur["account_ref"] = ref
                self.db.record("system_events", cur, "LEGACY_VERIFIED", "经用户确认，已用原单回报验证旧委托账户")
            cur["t"] = min(int(time.time()), cur["deadline"])
            done = live.settle(db, cur, o, order, trades)
            if done:
                snapshot(db, cur)
                cur.update(needs_check=True, admitted=False)
                if cur.get("ending"):
                    finish(db, cur, cur.pop("ending") == "stop")
                    if cur["positions"]:
                        cur["latest"] = "会话已结束，交易所仍有持仓，本地止损已停止"
                        db.record("system_events", cur, "PROTECTION_OFF", cur["latest"])
            else:
                # Query first, cancel only a known still-open original order.
                cancel = ((o.get("cancel_requested") or time.time() - o.get("sending_at", time.time()) > 10)
                          and o.get("cancel_attempts", 0) < 3 and time.time() >= o.get("cancel_after", 0))
                o["retry"] = time.time() + 2
                if cancel:
                    o.update(cancel_attempts=o.get("cancel_attempts", 0) + 1, cancel_after=time.time()+10)
                    db.record("system_events", cur, "CANCEL_REQUEST", "撤销原委托，等待终态", o["symbol"],
                              {"client_id": o["client_id"]})
                live.save(db, o, o["stage"])
                if trades:
                    snapshot(db, cur)
            db.save(cur)
        if cancel:
            venue.cancel(o)

    def order_error(self, cid, attempted, err):
        msg = safe_error(err)
        with self.lock, self.db.db:
            cur = self.db.load(cid)
            actual = live.pending(self.db, cid)
            if not actual or actual["client_id"] != attempted["client_id"]:
                return
            old_error = actual.get("error")
            actual["error"] = msg
            if actual["stage"] == "QUEUED":
                if attempted.get("calculation"):
                    actual["calculation"] = {**attempted["calculation"], "final_amount": 0,
                                             "final_pct": 0, "estimated_fee": 0, "reason": msg,
                                             "precision_status": "提交前检查拒绝"}
                live.save(self.db, actual, "REJECTED")
                cur.update(lifecycle_status="PAUSED", admitted=False, needs_check=True,
                           recovery_required=True)
            else:
                actual["retry"] = time.time() + 15
                live.save(self.db, actual, "UNKNOWN")
                cur.update(lifecycle_status="PAUSED", admitted=False, needs_check=True, recovery_required=True)
            if old_error != msg:
                self.db.record("system_events", cur, actual["stage"], msg, actual["symbol"],
                               {"client_id": actual["client_id"], "decision_id": actual.get("decision_id"),
                                "calculation": actual.get("calculation")})
            cur["latest"] = msg
            self.db.save(cur)
