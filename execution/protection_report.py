"""Bounded local recovery evidence. Never export credentials or raw exchange data."""
import json
import time

STAGES = {"PLANNED":"等待发送", "SENDING":"发送前已持久化", "ACCEPTED":"请求受理待查询",
          "LIVE":"查询为待触发", "UNKNOWN":"结果未知，先查原单", "CANCEL_PENDING":"撤销待确认",
          "TRIGGERED":"已触发，成交与账户待核对", "CANCELED":"已确认取消", "FAILED":"保护触发失败"}


def report(store, session_id, client_id, before=0, limit=100):
    if not isinstance(before,int) or isinstance(before,bool) or before < 0:
        raise ValueError("时间线游标无效")
    if not 1 <= limit <= 200:
        raise ValueError("时间线数量无效")
    if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='hosted_stops'").fetchone():
        raise ValueError("没有可读取的保护记录")
    raw=store.db.execute("SELECT body FROM hosted_stops WHERE client_id=?",(client_id,)).fetchone()
    if not raw:
        raise ValueError("保护记录不存在")
    order=json.loads(raw[0])
    if order["scope"][0] != session_id:
        raise ValueError("保护记录与所选会话不一致")
    state=store.load(session_id)
    if not state:
        raise ValueError("原交易会话缺失，不能生成核对报告")
    rows=store.db.execute("""SELECT id,stage,body FROM hosted_stop_events
        WHERE client_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT ?""",(client_id,before,before,limit+1)).fetchall()
    more=len(rows)>limit;rows=rows[:limit]
    events=[]
    for event_id, stage, raw in reversed(rows):
        body=json.loads(raw)
        events.append(dict(id=event_id, stage=stage, label=STAGES.get(stage,"未知状态"),
            recorded_at=body.get("recorded_at"), exchange_time=body.get("exchange_time") or None,
            quantity=body.get("quantity"), stop_price=body.get("stop_price"),
            remaining_quantity=body.get("remaining_quantity"), child_count=len(body.get("children",[])),
            cancel_attempts=body.get("cancel_attempts",0), released=bool(body.get("released")),
            maintenance_failed=bool(body.get("maintenance_error"))))
    if order.get("released"):
        guidance="原保护已核对释放；剩余持仓需接管，恢复普通交易前重新验收。"
    elif order["stage"] == "PLANNED":
        guidance="原意图尚未发送。检查未通过的参数；可在界面撤销本地意图，不会请求平台撤单。"
    elif order["stage"] in ("UNKNOWN","SENDING","ACCEPTED"):
        guidance="按原客户端标识查询；结果不明时禁止重新创建保护。"
    elif order["stage"] == "CANCEL_PENDING":
        guidance="先查询原单。确认仍待触发且冷却结束后可有限重试；三次上限后在平台人工核对。"
    elif order["stage"] == "TRIGGERED":
        guidance="触发不代表成交或平仓；核对所有子订单、手续费与余额后才能释放。"
    else:
        guidance="核对原单与专用账户余额；不要通过删除记录或恢复旧数据库解除阻断。"
    children=[]
    child_rows=store.db.execute("SELECT body FROM venue_orders WHERE json_extract(body,'$.parent_stop')=? ORDER BY rowid LIMIT 101",(client_id,)).fetchall()
    for child_raw, in child_rows[:100]:
        child=json.loads(child_raw)
        receipt=child.get("receipt")
        children.append(dict(stage=child.get("stage"),
            receipt={k:receipt.get(k) for k in ("qty","price","nominal","fee","slippage","pnl")}
                if isinstance(receipt,dict) else None))
    return dict(schema_version=1, generated_at=time.time(), session_id=session_id, client_id=client_id,
                platform=order["scope"][1], environment=order["scope"][2], product=order["scope"][3],
                symbol=order["symbol"], stage=order["stage"], guidance=guidance,
                events=events, children=children, children_truncated=len(child_rows)>100,
                has_more=more, next_before=rows[-1][0] if more else None,
                real_funds_verified=False, platform_integration_verified=False,
                evidence_scope="本机记录，不代替平台账户联调或实盘验收")
