"""Capability declarations describe evidence, never create account authority."""
from copy import deepcopy


def registry():
    rows=[]
    for name in ("okx", "binance", "gate"):
        rows.append(dict(exchange=name, product="spot", public_market=True,
            paper=True, demo=name!="gate", live=name!="gate",
            private_adapter="existing_unverified" if name!="gate" else "blocked",
            protocol_tests="offline_only", platform_integration_verified=False,
            real_funds_verified=False,
            reason="真实账户及成交验收后移，尚非 Stable" if name!="gate" else
                   "Gate 当前仅公开现货行情和模拟；私有执行器与保护流程未验收。批量行情缺少源时间时拒绝动态入场"))
    return deepcopy(rows)


def require_session(c):
    name,product,execution=(c[k] for k in ("exchange","product","execution"))
    if name not in ("okx","binance","gate"):
        raise ValueError("主交易平台无效")
    if name=="gate" and (product!="spot" or execution!="paper"):
        raise ValueError("Gate 当前仅开放现货模拟，真实与 demo 执行未验收")


def switch_blockers(db):
    from execution import live
    import json
    blockers=[]
    current=db.load()
    if current and current["lifecycle_status"] not in ("COMPLETED","STOPPED"):
        blockers.append("请先结束当前会话，再切换主平台")
    if live.unresolved(db):blockers.append("存在未完订单，须在原平台查单和对账")
    if live.hosted_pending(db):blockers.append("存在待核对托管保护单，须完成原账户交接")
    for row in db.db.execute("SELECT state FROM challenges"):
        s=json.loads(row[0])
        if s.get("config",{}).get("execution","paper")!="paper" and (
                s.get("positions") or s.get("needs_check") or s.get("recovery_required") or s.get("pending")):
            blockers.append(f"会话 #{s['id']} 有真实/demo 持仓或待核对资产，须先完成原账户交接")
    return blockers
