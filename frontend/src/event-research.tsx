import React,{useState} from "react";
import {Panel,Field,Table,api,useUI,type Row} from "./shared";

export function EventResearchPanel(){
  const [values,setValues]=useState({search:"",slug:"",limit:20,pages:1});
  const [data,setData]=useState<Row|null>(null);
  const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  const change=(key:string,value:string|number)=>{setValues(p=>({...p,[key]:value}));setData(null);setError("");};
  const load=async()=>{
    setBusy(true);setData(null);setError("");
    try{setData(await api("research/events",{provider:"polymarket",...values}));}
    catch(e){setError(e instanceof Error?e.message:"事件市场读取失败");}
    finally{setBusy(false);}
  };
  const stamp=(value:unknown)=>typeof value==="number"?new Date(value*1000).toLocaleString("zh-CN"):"未知";
  return <Panel title="Polymarket 事件市场发现" cap="READ-ONLY EVENT RESEARCH">
    <div className="pad" data-event-research>
      <p>读取官方公开市场元数据，不需要 API Key。仅查询限定分页内的样本，不承诺已发现所有市场或存在特定币种/周期。Gate 事件专用接口保留待验证，默认禁用。</p>
      <fieldset disabled={busy} style={{border:0,padding:0,margin:0,minWidth:0}}><div className="formgrid">
        <Field label="事件标题关键词（在样本内筛选）"><input aria-label="事件标题关键词" value={values.search} onChange={e=>change("search",e.target.value)}/></Field>
        <Field label="指定市场 slug（可留空）"><input aria-label="事件市场 slug" value={values.slug} onChange={e=>change("slug",e.target.value)}/></Field>
        <Field label="每页市场数（1–50）"><input aria-label="事件每页数量" type="number" min="1" max="50" value={values.limit} onChange={e=>change("limit",Number(e.target.value))}/></Field>
        <Field label="读取页数（1–3）"><input aria-label="事件页数" type="number" min="1" max="3" value={values.pages} onChange={e=>change("pages",Number(e.target.value))}/></Field>
      </div></fieldset>
      <div className="buttons"><button disabled={busy} onClick={load}>{busy?"正在读取事件市场…":"查询 Polymarket 公开市场"}</button></div>
      {!data&&!error&&!busy&&<p>尚未查询事件市场。该入口不创建交易会话或订单。</p>}
      {error&&<p role="alert">{error}</p>}
      {data&&<div data-event-result>
        <p>来源：{data.source} · 接收于 {stamp(data.received_at)} · {data.cached?"30秒内元数据缓存":"本次公开查询"}</p>
        <p>读取 {data.pages_requested} 页 / 检查 {data.scanned} 条 / 显示 {data.shown} 个二元市场 / 重复 {data.duplicates} 条。</p>
        <p>当前仅有元数据：可成交报价、费用、结算资产、官方结算及模拟闭环尚未验证；市场开放标志不代表账户资格或交易授权。标题和外部结算说明仅按文本显示。</p>
        <Table heads={["市场 / 标识","两个结果","源更新时间 / 到期时间","最小份额 / 价格档位","详情"]} rows={data.rows.map((row:Row)=>[
          <span style={{display:"block",maxWidth:320,whiteSpace:"normal",overflowWrap:"anywhere"}}>{row.title}<br/><small>市场 #{row.market_id}</small></span>,row.outcomes.map((v:Row)=>v.name).join(" / "),stamp(row.source_updated_at)+" / "+stamp(row.ends_at),
          String(row.minimum_size??"未知")+" / "+String(row.price_tick??"未知"),
          <button onClick={()=>useUI.getState().show({title:"事件市场标识 · "+row.market_id,summary:"市场、事件、条件及结果 Token 保持独立；未获得交易或结算验证。",data:row})}>查看市场标识</button>
        ])}/>
        {Object.keys(data.rejections).length>0&&<p>未展示原因：{Object.entries(data.rejections).map(([reason,count])=>reason+" "+count).join("；")}</p>}
      </div>}
    </div>
  </Panel>;
}
