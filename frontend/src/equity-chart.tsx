import React,{useEffect,useRef,useState} from "react";
import {createChart,AreaSeries,ColorType,createSeriesMarkers,type UTCTimestamp,type ISeriesApi,type Time,type IPriceLine,type ISeriesMarkersPluginApi} from "lightweight-charts";
import {Panel,type Row} from "./shared";
import {prepareCurve,replayCurve} from "./chart-data";
import {ReplayCandles} from "./replay-candles";

export function Curve({d}:{d:Row}) {
  const ref=useRef<HTMLDivElement>(null);
  const instance=useRef<{chart:ReturnType<typeof createChart>;series:ISeriesApi<"Area">;markers:ISeriesMarkersPluginApi<Time>}|null>(null);
  const [range,setRange]=useState(24),[light,setLight]=useState(document.body.classList.contains("light")),[error,setError]=useState("");
  const [cutoff,setCutoff]=useState<number|null>(null),[playing,setPlaying]=useState(false),[symbol,setSymbol]=useState("BTC");
  const all=prepareCurve(d,range),data=replayCurve(all,cutoff);
  const capital=d.state?.config?.capital,target=d.state?.config?.profile==="challenge"?capital*2:null;
  const version=JSON.stringify([data.points,data.markers,capital,target]);
  const sessionId=d.state?.id;
  useEffect(()=>{setCutoff(null);setPlaying(false);},[sessionId]);
  useEffect(()=>{const observer=new MutationObserver(()=>setLight(document.body.classList.contains("light")));observer.observe(document.body,{attributes:true,attributeFilter:["class"]});return ()=>observer.disconnect();},[]);
  useEffect(()=>{
    if(!ref.current)return;
    try {
      if(!document.createElement("canvas").getContext("2d"))throw Error("Canvas unavailable");
      const chart=createChart(ref.current,{autoSize:true,layout:{background:{type:ColorType.Solid,color:"transparent"},attributionLogo:true},grid:{vertLines:{color:"#7888a51a"},horzLines:{color:"#7888a525"}},timeScale:{timeVisible:true,secondsVisible:false},handleScroll:false,handleScale:false});
      const series=chart.addSeries(AreaSeries,{lineColor:"#9885ff",topColor:"#9581ff44",bottomColor:"#9581ff02",lineWidth:2});
      const markers=createSeriesMarkers(series,[]);instance.current={chart,series,markers};
      return ()=>{instance.current=null;chart.remove();};
    } catch {setError("图表暂时无法初始化，账本不受影响。");}
  },[]);
  useEffect(()=>{instance.current?.chart.applyOptions({layout:{textColor:light?"#56657b":"#99a8bf"}});},[light]);
  useEffect(()=>{
    const current=instance.current;if(!current)return;
    try {
      current.series.setData(data.points.map(p=>({...p,time:p.time as UTCTimestamp})));
      current.markers.setMarkers(data.markers.map(m=>({...m,time:m.time as UTCTimestamp})));
      const lines:IPriceLine[]=[];
      if(typeof capital==="number"&&Number.isFinite(capital))lines.push(current.series.createPriceLine({price:capital,color:"#8391aa",lineWidth:1,lineStyle:2,title:"初始"}));
      if(typeof target==="number"&&Number.isFinite(target))lines.push(current.series.createPriceLine({price:target,color:"#edaa60",lineWidth:1,lineStyle:2,title:"目标"}));
      current.chart.timeScale().fitContent();setError("");
      return ()=>{if(instance.current===current)for(const line of lines)current.series.removePriceLine(line);};
    } catch {setError("图表暂时无法渲染，账本记录仍可查看。");}
  },[version]);
  useEffect(()=>{
    if(!playing)return;
    const next=all.points.find(p=>p.time>(cutoff??0));
    if(!next){setPlaying(false);return;}
    const timer=setTimeout(()=>setCutoff(next.time),250);
    return ()=>clearTimeout(timer);
  },[playing,cutoff,JSON.stringify(all.points.map(p=>p.time))]);
  const index=Math.max(0,all.points.reduce((index,p,i)=>p.time<=(cutoff??Infinity)?i:index,-1));
  const step=(delta:number)=>{setPlaying(false);setCutoff(all.points[Math.max(0,Math.min(all.points.length-1,index+delta))]?.time??null);};
  return <Panel title="账户净值" cap="EQUITY / USDT">
    <div className="plotbar"><span>● 策略净值</span><select aria-label="净值显示范围" value={range} onChange={e=>{setRange(+e.target.value);setCutoff(null);setPlaying(false);}}>{[1,6,24].map(n=><option key={n} value={n}>{n} 小时</option>)}</select></div>
    <div className="buttons"><button disabled={!all.points.length} onClick={()=>{setPlaying(false);setCutoff(cutoff===null?all.points.at(-1)!.time:null);}}>{cutoff===null?"开启图表回放":"返回最新图表"}</button></div>
    {cutoff!==null&&<div className="pad">
      <p>图表回放仅改变显示，不暂停交易或提交订单。当前 {new Date(cutoff*1000).toLocaleString("zh-CN")}</p>
      <input aria-label="图表回放位置" type="range" min={0} max={Math.max(0,all.points.length-1)} value={index} onChange={e=>{setPlaying(false);const point=all.points[+e.target.value];if(point)setCutoff(point.time);}} style={{width:"100%"}}/>
      <div className="buttons"><button onClick={()=>step(-1)}>上一时点</button><button onClick={()=>{if(index===all.points.length-1)setCutoff(all.points[0].time);setPlaying(!playing);}}>{playing?"暂停回放":"播放回放"}</button><button onClick={()=>step(1)}>下一时点</button></div>
    </div>}
    <div className="chart" ref={ref} data-chart-theme={light?"light":"dark"} data-chart-points={data.points.length} data-chart-markers={data.markers.length} data-chart-last={data.points.at(-1)?.value}/>
    {!data.points.length&&<p className="pad">暂无有效净值数据</p>}
    {!!data.rejected&&<p className="pad">已排除 {data.rejected} 条无效或未来时点记录，请核对数据源。</p>}
    {error&&<p role="alert" className="pad">{error}</p>}
    {cutoff!==null&&d.state?.config?.source==="history"&&<div className="pad">
      <label>回放币种 <select aria-label="K线回放币种" value={symbol} onChange={e=>setSymbol(e.target.value)}>{["BTC","ETH","SOL","DOGE","XRP","AVAX","LINK","ADA"].map(s=><option key={s}>{s}</option>)}</select></label>
      <ReplayCandles id={d.state.id} cutoff={cutoff} symbol={symbol} light={light}/>
    </div>}
    {cutoff!==null&&d.state?.config?.source!=="history"&&<p className="pad">此会话只回放已记录净值，未保存的实时 K 线不回填为历史事实。</p>}
    <small className="pad"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></small>
  </Panel>;
}
