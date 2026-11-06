import React,{useState} from "react";
import {Panel,Field,Table,api,useUI,type Row} from "./shared";

export function EventResearchPanel(){
  const [values,setValues]=useState({lifecycle:"open",search:"",slug:"",limit:20,pages:1});
  const [data,setData]=useState<Row|null>(null);
  const [selected,setSelected]=useState<Row|null>(null);
  const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  const change=(key:string,value:string|number)=>{setValues(p=>({...p,[key]:value}));setData(null);setSelected(null);setError("");};
  const load=async()=>{
    setBusy(true);setData(null);setSelected(null);setError("");
    try{setData(await api("research/events",{provider:"polymarket",...values}));}
    catch(e){setError(e instanceof Error?e.message:"事件市场读取失败");}
    finally{setBusy(false);}
  };
  const stamp=(value:unknown)=>typeof value==="number"?new Date(value*1000).toLocaleString("zh-CN"):"未知";
  return <Panel title="Polymarket 事件市场发现" cap="READ-ONLY EVENT RESEARCH">
    <div className="pad" data-event-research>
      <p>读取官方公开市场元数据，不需要 API Key。仅查询限定分页内的样本，不承诺已发现所有市场或存在特定币种/周期。Gate 事件专用接口保留待验证，默认禁用。</p>
      <fieldset disabled={busy} style={{border:0,padding:0,margin:0,minWidth:0}}><div className="formgrid">
        <Field label="事件市场状态"><select aria-label="事件市场状态" value={values.lifecycle} onChange={e=>change("lifecycle",e.target.value)}><option value="open">开放市场</option><option value="closed">已关闭市场（不等于已结算）</option></select></Field>
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
        <p>发现列表仅有元数据。可在详情中读取公开盘口、基准费率和官方结算状态；完整费用模型、结算资产与模拟闭环仍待验证。市场开放标志不代表账户资格或交易授权。</p>
        <Table heads={["市场 / 标识","两个结果","源更新时间 / 到期时间","最小份额 / 价格档位","详情"]} rows={data.rows.map((row:Row)=>[
          <span style={{display:"block",maxWidth:320,whiteSpace:"normal",overflowWrap:"anywhere"}}>{row.title}<br/><small>市场 #{row.market_id}</small></span>,row.outcomes.map((v:Row)=>v.name).join(" / "),stamp(row.source_updated_at)+" / "+stamp(row.ends_at),
          String(row.minimum_size??"未知")+" / "+String(row.price_tick??"未知"),
          <div className="buttons"><button onClick={()=>useUI.getState().show({title:"事件市场标识 · "+row.market_id,summary:"市场、事件、条件及结果 Token 保持独立；元数据不是交易或结算授权。",data:row})}>查看市场标识</button>
          <button onClick={()=>setSelected(row)}>查询公开详情</button></div>
        ])}/>
        {selected&&<EventMarketDetails key={selected.market_id} market={selected}/> }
        {Object.keys(data.rejections).length>0&&<p>未展示原因：{Object.entries(data.rejections).map(([reason,count])=>reason+" "+count).join("；")}</p>}
      </div>}
    </div>
  </Panel>;
}


function EventMarketDetails({market}:{market:Row}){
  const [index,setIndex]=useState(0);
  const [busy,setBusy]=useState("");const [error,setError]=useState("");
  const [quote,setQuote]=useState<Row|null>(null);const [resolution,setResolution]=useState<Row|null>(null);
  const time=(value:unknown)=>typeof value==="number"?new Date(value*1000).toLocaleString("zh-CN"):"未知";
  const n=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?String(value):"未知";
  const read=async(kind:"quote"|"resolution")=>{
    setBusy(kind);setError("");if(kind==="quote")setQuote(null);else setResolution(null);
    try{
      const result=await api("research/events/"+kind,{market_id:market.market_id,...(kind==="quote"?{outcome_index:index}:{})});
      if(kind==="quote")setQuote(result);else setResolution(result);
    }catch(e){setError(e instanceof Error?e.message:"公开详情读取失败");}
    finally{setBusy("");}
  };
  return <section className="panel pad" data-event-details={market.market_id}>
    <h3>公开详情 · 市场 #{market.market_id}</h3>
    <p>{market.title}</p>
    <p>以下为查询时快照，不是持续行情订阅；没有订单提交、钱包、实际资金兑付或自动结算操作。</p>
    <Field label="盘口结果选择"><select aria-label="盘口结果选择" disabled={!!busy} value={index} onChange={e=>{setIndex(Number(e.target.value));setQuote(null);setError("");}}>
      {market.outcomes.map((o:Row,i:number)=><option key={o.token_id} value={i}>{o.name}</option>)}
    </select></Field>
    <div className="buttons">
      <button disabled={!!busy} onClick={()=>read("quote")}>{busy==="quote"?"正在读取盘口…":"读取盘口与基准费率"}</button>
      <button disabled={!!busy} onClick={()=>read("resolution")}>{busy==="resolution"?"正在查询结算…":"查询官方结算"}</button>
    </div>
    {error&&<p role="alert">{error}</p>}
    {quote&&<div data-event-quote>
      <p>结果 {quote.outcome} · 源时间 {time(quote.source_timestamp)} · 接收时间 {time(quote.received_at)} · {quote.cached?"3秒内缓存（未重置源时间）":"本次公开快照"}</p>
      <p>买一 {n(quote.best_bid)} / 卖一 {n(quote.best_ask)} / 价差 {n(quote.spread)} · {quote.quote_available?"已核验双边盘口快照":"单边或空盘口，不可作为双边报价"}</p>
      <p>最小份额 {n(quote.minimum_size)} · 价格档位 {n(quote.price_tick)} · 官方基准费率 {n(quote.base_fee_bps)} bps。{quote.fee_note}</p>
      <p>{quote.note} 结算资产尚未核验，不将报价标为 USDT；模拟与真实订单均未启用。</p>
      <Table heads={["买盘价格","买盘份额","卖盘价格","卖盘份额"]} rows={Array.from({length:Math.max(quote.bids.length,quote.asks.length)},(_,i)=>[
        n(quote.bids[i]?.price),n(quote.bids[i]?.size),n(quote.asks[i]?.price),n(quote.asks[i]?.size)
      ])}/>
    </div>}
    {resolution&&<div data-event-resolution>
      <p>官方状态 {resolution.status} · {resolution.settlement_verified?"官方接口结算证据已核验":"未确认结算"} · 接收时间 {time(resolution.received_at)} · {resolution.cached?"15秒内缓存（保留原时间）":"本次官方查询"}</p>
      <p>{resolution.reason}</p>
      <p>源更新时间 {time(resolution.source_updated_at)} · 完成时间 {time(resolution.resolved_at)} · 尚未进行链上复核或实际兑付。</p>
      {resolution.payouts&&<Table heads={["结果","官方每份额兑付（USDC，按接口单位换算）"]} rows={resolution.payouts.map((p:Row)=>[p.outcome,n(p.payout)])}/>}
    </div>}
  </section>;
}
