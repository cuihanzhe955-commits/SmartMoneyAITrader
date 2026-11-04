"""Read-only acceptance evidence. Reports never arm trading or grant authority."""
import copy
import json
import time
from execution.identity import digest, position_version, scope
from execution import live
from execution.protection import audit_protection
from events.store import encode


def token(state):
    return digest([scope(state), state["config"], state.get("revision"), position_version(state)])


def inspect_session(rt, session_id):
    from terminal.runtime import safe_error, protection_ready
    if not rt.health_mutex.acquire(blocking=False):
        raise ValueError("只读验收正在进行，请等待本轮结果")
    try:
        with rt.lock:
            state = rt.db.load(session_id)
            if not state:
                raise ValueError("会话不存在")
            if state["config"].get("execution") not in ("demo", "live") or state["config"].get("product") != "spot":
                raise ValueError("请先创建交易所现货会话；历史和本地模拟不能作为实盘验收")
            state = copy.deepcopy(state)
            rt.check_binding(state)
            binding, version = rt.account_ref(state["config"]), token(state)
        started = int(time.time())
        checks = []

        def check(key, name, work):
            try:
                details = work()
                checks.append(dict(key=key, name=name, status="PASS", message="通过", details=details))
            except Exception as error:
                checks.append(dict(key=key, name=name, status="FAIL", message=safe_error(error)))

        venue = rt.venue(state["config"])

        def permissions():
            proof = venue.permission_check()
            if state.get("venue_account_id", proof["venue_account_id"]) != proof["venue_account_id"]:
                raise ValueError("当前账户与原会话授权账户不同")
            return {"identity_match": True, "permissions": "只读与现货交易；不含提现"}

        check("permissions", "账户身份与最小权限", permissions)
        check("rules", "交易所现货规则", venue.market_check)
        check("balance", "专用账户资金与未结委托", lambda: venue.audit(state))

        def algos():
            if venue.name != "okx":
                raise ValueError("此版本尚未完整核验该平台的条件单清单")
            inventory = venue.algo_inventory()
            audit = audit_protection(state, inventory)
            if inventory:
                # Keep operational identifiers in the local report only.
                checks.append(dict(key="algo_inventory", name="保护单状态与持仓数量", status="FAIL",
                                   message="；".join(audit["issues"][:3]), details=audit))
                raise ValueError("存在未核对条件单，请在交易所核对后重新检查")
            if audit["positions"]:
                checks.append(dict(key="algo_positions", name="持仓托管保护缺口", status="WARN",
                                   message="；".join(audit["issues"][:3]), details=audit))
            return audit

        check("algos", "条件单与保护状态核对", algos)
        check("quotes", "持仓盘口时效", lambda: {
            symbol: {"bid": q[0], "ask": q[1], "quote_time": q[2]}
            for symbol in (state["positions"] or {"BTC": None})
            for q in [venue.quote(symbol)]})

        with rt.lock, rt.db.db:
            current = rt.db.load(session_id)

            def ledger():
                if rt.db.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("数据库完整性检查失败")
                if live.unresolved(rt.db):
                    raise ValueError("存在未确认订单，必须先查询原单并完成对账")
                if not current or token(current) != version or rt.account_ref(current["config"]) != binding:
                    raise ValueError("检查期间账户、配置或持仓发生变化，请重新检查")
                return {"database": "ok", "unresolved_orders": 0, "snapshot_unchanged": True}

            check("ledger", "本地账本、订单与检查快照", ledger)
            monitoring = bool(current and current.get("local_armed") and
                              current.get("lifecycle_status") == "RUNNING" and
                              current["positions"] and protection_ready(current))
            checks.append(dict(key="protection", name="止损保障", status="WARN",
                               message="仅本地策略止损；退出、暂停或断网后不保证执行",
                               details={"local_monitoring": monitoring,
                                        "exchange_protection_verified": False}))
            report = dict(id=digest([session_id, started, time.time_ns()])[:24],
                          session_id=session_id, exchange=state["config"]["exchange"],
                          environment=state["config"]["execution"], engine=state["config"]["engine"],
                          started_at=started, finished_at=int(time.time()), scope_hash=version,
                          read_only=True, real_funds_verified=False, authorizes_trading=False,
                          runtime_id=rt.runtime_id, requires_recheck=False, recheck_reasons=[],
                          status="BLOCKED" if any(c["status"] == "FAIL" for c in checks) else "READ_ONLY_PASSED",
                          checks=checks,
                          remaining=["真实资金试单尚未获授权、未执行",
                                     "交易所托管保护单创建、触发、撤销及重启恢复尚未验收",
                                     "账户及地区使用资格需符合交易所要求；API 连通不能证明资格"])
            rt.db.db.execute("INSERT INTO acceptance_reports VALUES(?,?,?,?)",
                            (report["id"], session_id, report["finished_at"], encode(report)))
            return report
    finally:
        rt.health_mutex.release()


def latest_report(rt, session_id):
    row = rt.db.db.execute("SELECT body FROM acceptance_reports WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
                           (session_id,)).fetchone()
    if not row:
        return None
    report = json.loads(row[0])
    reasons = []
    if report.get("runtime_id") != rt.runtime_id:
        reasons.append("程序已重启，旧报告需要重新核验")
    if not 0 <= time.time() - report.get("finished_at", 0) < 60:
        reasons.append("报告已超过 60 秒有效展示期，或本机时间发生变化")
    current = rt.db.load(session_id)
    if not current or token(current) != report.get("scope_hash"):
        reasons.append("账户、配置或持仓已变化")
    elif current["config"].get("execution") != "paper":
        try:
            rt.check_binding(current)
        except ValueError:
            reasons.append("原账户凭据绑定需要重新核验")
    report.update(requires_recheck=bool(reasons), recheck_reasons=reasons)
    return report
