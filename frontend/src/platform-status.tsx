import React from "react";
import {useQuery} from "@tanstack/react-query";
import {Panel,Table,api,txt,type Row} from "./shared";

export function PlatformStatus() {
  const q=useQuery({queryKey:["platforms"],queryFn:()=>api("platforms"),refetchInterval:2000});
  return <Panel title="主平台与隔离状态" cap="SINGLE ACTIVE PLATFORM">
    <div className="pad" data-platform-status>
      {q.isPending&&<p>正在核对本地平台状态…</p>}
      {q.error&&<p role="alert">读取平台状态失败：{q.error.message}</p>}
      {q.data&&<>
        <p>{q.data.active?`当前会话 #${q.data.active.session_id} · ${q.data.active.exchange.toUpperCase()} · ${txt(q.data.active.execution)} · ${txt(q.data.active.product)} · ${txt(q.data.active.status)}`:"尚无交易会话"}</p>
        <p>任一时刻仅一个会话运行。请结束当前会话后，在创建会话中选择新平台；新预算、订单、持仓和风控独立建立，旧记录保留。</p>
        {q.data.switch_blockers.length>0?<div role="status">切换前须处理：{q.data.switch_blockers.join("；")}</div>:<p>本地切换检查通过，可创建新会话。此状态不代表账户授权或实盘验收。</p>}
        <Table heads={["现货平台","公开行情 / 模拟","账户执行适配","真实资金验收","说明"]} rows={q.data.platforms.map((r:Row)=>[
          r.exchange.toUpperCase(),"已实现，仍受平台访问及数据质量限制",r.live?"已有适配，启动须独立预检与授权":"关闭",r.real_funds_verified?"通过":"未验收",r.reason
        ])}/>
      </>}
    </div>
  </Panel>;
}
