import React, {useState} from "react";
import {Panel,Field,Table,api,f,useUI,type Row} from "./shared";

export function MarketResearch() {
  const [values,setValues]=useState<Row>({exchange:"okx",budget:10,fee_pct:.1,minimum:1,min_volume:1000000,max_spread_pct:.3,max_change_pct:50,search:"",whitelist:"",blacklist:"",limit:25});
  const [data,setData]=useState<Row|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const change=(key:string,value:unknown)=>{setValues(v=>({...v,[key]:value}));setData(null);setError("");};
  const load=async()=>{
    setBusy(true);setData(null);setError("");
    const names=(s:string)=>s.split(/[,，\s]+/).filter(Boolean);
    try {setData(await api("research/markets",{...values,whitelist:names(values.whitelist),blacklist:names(values.blacklist)}));}
    catch(e) {setError(e instanceof Error?e.message:"公开行情读取失败");}
    finally {setBusy(false);}
  };
  return <Panel title="动态市场发现与预算预检" cap="PUBLIC SPOT RESEARCH">
    <div className="pad">
      <p>批量读取公开现货行情，按 24 小时振幅排序。仅研究，不修改会话、账户或订单；运行中扫描器仍使用原监控池。Gate 为公开数据研究入口。</p>
      <fieldset disabled={busy} style={{border:0,padding:0,margin:0,minWidth:0}}><div className="formgrid">
        <Field label="公开行情平台"><select aria-label="研究行情平台" value={values.exchange} onChange={e=>change("exchange",e.target.value)}>{["okx","binance","gate"].map(n=><option key={n} value={n}>{n.toUpperCase()}</option>)}</select></Field>
        <Field label="搜索币种 / 交易对"><input aria-label="研究搜索币种" value={values.search} onChange={e=>change("search",e.target.value)}/></Field>
        {[["单笔研究预算 USDT","budget"],["手续费预留 %","fee_pct"],["软件最小金额 USDT","minimum"],["最低24小时成交额 USDT","min_volume"],["最大盘口价差 %","max_spread_pct"],["最大24小时涨跌幅绝对值 %","max_change_pct"],["显示数量（1–200）","limit"]].map(([label,key])=><Field key={key} label={label}><input aria-label={label} type="number" step="any" value={values[key]} onChange={e=>change(key,Number(e.target.value))}/></Field>)}
        <Field label="白名单（空为不限）"><input aria-label="研究白名单" placeholder="BTC, ETH" value={values.whitelist} onChange={e=>change("whitelist",e.target.value)}/></Field>
        <Field label="黑名单"><input aria-label="研究黑名单" placeholder="币种或 USDT 交易对，以逗号分隔" value={values.blacklist} onChange={e=>change("blacklist",e.target.value)}/></Field>
      </div></fieldset>
      <div className="buttons"><button disabled={busy} onClick={load}>{busy?"正在读取公开行情…":"发现并预检交易对"}</button></div>
      {!data&&!error&&!busy&&<p>尚未查询。点击按钮后读取平台公开数据；不需要 API Key。</p>}
      {error&&<p role="alert">{error}</p>}
      {data&&<div data-discovery-result={data.exchange}>
        <p>{data.source} · 接收于 {new Date(data.received_at*1000).toLocaleString("zh-CN")} · {data.cached?"使用60秒内批量缓存":"新批量行情"}</p>
        <p><b>发现 {data.scope} 对 / 名单与搜索匹配 {data.matched} 对 / 通过研究筛选 {data.eligible} 对 / 显示 {data.shown} 对</b></p>
        <p>{data.note} 行情缺少平台时间、过期或规则不完整时，显示拒绝原因。盘口深度及真实账户可用余额尚未核验。</p>
        <Table heads={["交易对","24h振幅 / 涨跌","成交额 USDT","价差","预估名义金额 / 含费 USDT","研究结果"]} rows={data.rows.map((r:Row)=>[
          r.symbol,f(r.amplitude_pct)+"% / "+f(r.change_pct)+"%",f(r.quote_volume,0),f(r.spread_pct,3)+"%",
          r.budget?f(r.budget.notional,6)+" / "+f(r.budget.total,6):"—",
          <button onClick={()=>useUI.getState().show({title:r.symbol+" · 公开研究预检",summary:r.budget?"研究预算 "+f(r.budget.allocated,6)+" USDT；预估名义金额 "+f(r.budget.notional,6)+"，手续费预留 "+f(r.budget.fee_reserved,6)+"，合计 "+f(r.budget.total,6)+"，未用预算 "+f(r.budget.unused,6)+"。仅金额预检，不是下单授权。":r.reasons.join("；"),data:r})}>{r.eligible?"研究筛选通过 · 查看计算":r.reasons.join("；")}</button>
        ])}/>
        <p>筛除统计：{Object.entries(data.rejection_counts).map(([name,n])=>name+" "+n).join("；")||"无"}（一对可有多个原因）。</p>
        <p>批量行情缓存60秒，市场规则缓存10分钟；失败时不返回旧缓存冒充最新结果。</p>
      </div>}
    </div>
  </Panel>;
}
