"""Read-only ledger/closed-candle replay for bundled historical sessions."""
import json
from market.feeds import START,SYMBOLS,historical


def replay(db,session_id,symbol,as_of):
    if type(session_id) is not int or session_id<=0:raise ValueError("回放会话编号必须为正整数")
    s=db.load(session_id)
    if not s or s["config"]["source"]!="history":raise ValueError("K线原型仅支持内置历史会话；不回填实时或真实账户行情")
    if symbol not in SYMBOLS:raise ValueError("币种不在内置历史归档范围")
    if (type(as_of) is not int or as_of%60 or
        not s["start"]<=as_of<=min(s["t"],s["deadline"],START+86400)):
        raise ValueError("回放时点必须在会话已记录的已收盘分钟范围内")
    rows=historical(as_of)[symbol]
    if not rows or rows[-1][0]>as_of:raise ValueError("归档不完整或包含未来数据")
    def records(table):
        raw=db.db.execute("SELECT * FROM "+table+" WHERE challenge_id=? AND symbol=? AND t>=? AND t<=? ORDER BY t,id LIMIT 1001",
            (session_id,symbol,max(rows[0][0],s["start"]),as_of)).fetchall()
        return [dict(dict(v),data=json.loads(v["data"])) for v in raw[:1000]],len(raw)>1000
    fills,truncated=records("fills");decisions,decisions_truncated=records("decisions")
    return dict(session_id=session_id,symbol=symbol,as_of=as_of,source="项目内置 Binance 公开历史归档 + 本会话真实模拟账本",
        read_only=True,changes_sessions=False,candles=[dict(time=r[0],open=r[1],high=r[2],low=r[3],close=r[4]) for r in rows],
        fills=fills,decisions=decisions,truncated=truncated or decisions_truncated,
        note="显示截至选定时点的已记录数据，不重新运行策略；成交标记来自本会话账本。")
