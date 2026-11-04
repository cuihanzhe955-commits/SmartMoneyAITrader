"""Local demo integration prerequisites. No account requests or permissions writes."""
from execution.health import latest_report
from execution import live


def inspect_local(rt):
    with rt.lock:
        keys = rt.vault.values.get("okx/demo") or {}
        missing = [name for field,name in (("key","API Key"),("secret","Secret"),("passphrase","Passphrase"))
                   if not isinstance(keys.get(field),str) or not keys[field].strip()]
        state = rt.db.load()
        matching = bool(state and tuple(state["config"].get(k) for k in ("exchange","execution","product"))
                        == ("okx","demo","spot"))
        bound = False
        if matching:
            try:
                rt.check_binding(state)
                bound = True
            except ValueError:
                pass
        blocked = bool(live.unresolved(rt.db)) or live.hosted_pending(rt.db)
        report = latest_report(rt,state["id"]) if matching else None
        checked = bool(report and report["status"] == "READ_ONLY_PASSED" and not report["requires_recheck"]
                       and report["environment"] == "demo" and report["exchange"] == "okx")
        steps = [
            dict(key="credentials",name="模拟账户凭据",status="READY" if not missing else "ACTION_REQUIRED",
                 message="已在本机保存完整字段，尚不代表平台已接受凭据" if not missing else "请在下方交易所账户填写模拟环境的 " + "、".join(missing)),
            dict(key="session",name="当前模拟现货会话",status="READY" if matching and bound else "ACTION_REQUIRED",
                 message="当前会话已绑定 OKX 现货模拟环境" if matching and bound else "请先配置模拟凭据，并在自动交易页创建 OKX 现货模拟会话；不必启动"),
            dict(key="orders",name="未核对订单与保护记录",status="BLOCKED" if blocked else "READY",
                 message="请先查询原单并核对账户，不得通过删除记录解除阻断" if blocked else "本地未发现待处理订单阻断；平台状态仍需只读查询"),
            dict(key="health",name="只读平台预检",status="READY" if checked else "ACTION_REQUIRED",
                 message="当前报告在有效期内，仅证明当时只读检查通过" if checked else "点击运行模拟只读预检；账户、资金、规则或报告变化后重新检查"),
            dict(key="eligibility",name="账户与地区使用资格",status="USER_CHECK_REQUIRED",
                 message="请自行确认平台账户及地区资格；API 可访问不能代替资格确认"),
            dict(key="integration",name="平台成交生命周期验收",status="NOT_VERIFIED",
                 message="尚未通过平台模拟账户下单、触发、成交、费用及重启验收；本页不会执行这些操作"),
        ]
        return dict(read_only=True, local_only=True, authorizes_trading=False, platform_integration_verified=False,
                    real_funds_verified=False, session_id=state["id"] if matching else None,
                    can_run_readonly=not missing and matching and bound and not blocked,
                    prereqs_ready=not missing and matching and bound and not blocked and checked,
                    steps=steps)
