import React,{useEffect,useRef,useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {createChart,CandlestickSeries,ColorType,createSeriesMarkers,type UTCTimestamp} from "lightweight-charts";
import {api,Table,f,time,useUI,type Row} from "./shared";

export function ReplayCandles({id,cutoff,symbol,light}:{id:number;cutoff:number;symbol:string;light:boolean}) {
  const ref=useRef<HTMLDivElement>(null);
  const [error,setError]=useState("");
  const q=useQuery({queryKey:["session-replay",id,symbol,cutoff],queryFn:()=>api(`replay?session_id=${id}&symbol=${symbol}&as_of=${cutoff}`),gcTime:60000,staleTime:Infinity});
  useEffect(()=>{
    if (!ref.current||!q.data) return;
    let chart:ReturnType<typeof createChart>|undefined;
    try {
      if(!document.createElement("canvas").getContext("2d"))throw Error("Canvas unavailable");
      chart=createChart(ref.current,{autoSize:true,layout:{background:{type:ColorType.Solid,color:"transparent"},textColor:light?"#56657b":"#99a8bf",attributionLogo:true},grid:{vertLines:{color:"#7888a51a"},horzLines:{color:"#7888a525"}},timeScale:{timeVisible:true}});
      const series=chart.addSeries(CandlestickSeries,{upColor:"#39cb9b",downColor:"#f0798c",borderVisible:false,wickUpColor:"#39cb9b",wickDownColor:"#f0798c"});
      series.setData(q.data.candles.map((v:Row)=>({...v,time:v.time as UTCTimestamp})));
      const times=new Set(q.data.candles.map((v:Row)=>v.time));
      createSeriesMarkers(series,q.data.fills.filter((v:Row)=>times.has(v.t)&&["BUY","SELL"].includes(v.kind)).map((v:Row)=>({time:v.t as UTCTimestamp,position:v.kind==="BUY"?"belowBar" as const:"aboveBar" as const,color:v.kind==="BUY"?"#39cb9b":"#f0798c",shape:"circle" as const,text:v.kind==="BUY"?"买":"卖"})));
      chart.timeScale().fitContent();setError("");
    } catch {setError("K线无法渲染，账本记录仍可查看。");}
    return ()=>chart?.remove();
  },[q.data,light]);
  return <section aria-label="历史K线与成交回放">
    <p>历史 K 线原型 · {symbol}/USDT · 截至 {new Date(cutoff*1000).toLocaleString("zh-CN")}</p>
    {q.isPending&&<p>正在读取已记录的历史数据…</p>}
    {q.isError&&<p role="alert">回放数据读取失败：{q.error.message}</p>}
    <div ref={ref} className="chart" data-replay-candles={q.data?.candles.length||0} data-replay-fills={q.data?.fills.length||0}/>
    {error&&<p role="alert">{error}</p>}
    {q.data&&<><p>{q.data.source}。{q.data.note}</p>
      <Table heads={["已记录成交","方向","价格","数量","费用 USDT"]} rows={q.data.fills.slice(-50).map((v:Row)=>[time(v.t),v.kind==="BUY"?"买入":v.kind==="SELL"?"卖出":v.kind,f(v.data.price,6),f(v.data.qty,8),f(v.data.fee,6)])}
        click={i=>useUI.getState().show({title:"回放成交明细",data:q.data.fills.slice(-50)[i].data})}/>
      <Table heads={["最近决策","动作","原因"]} rows={q.data.decisions.slice(-10).map((v:Row)=>[time(v.t),v.kind,v.summary])}/>
      {(q.data.truncated||q.data.fills.length>50||q.data.decisions.length>10)&&<small>此处仅显示窗口内最近记录，完整流水见交易流水与决策中心。</small>}
    </>}
  </section>;
}
