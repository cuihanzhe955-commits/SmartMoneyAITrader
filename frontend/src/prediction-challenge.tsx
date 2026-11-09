import React,{useEffect,useState} from "react";
import {Panel,Field,Table,api,useUI,type Row} from "./shared";

const labels:Row={INITIALIZING:"正在准备",ACTIVE:"自动运行",PAUSED:"已暂停",STOPPING:"结束维护中",STOPPED:"已结束",COMPLETED:"目标完成",RESERVED:"已安排",QUEUED:"等待预测",PREDICTING:"预测中",WAITING:"等待官方结果",SETTLED:"已结算",FAILED:"失败尝试"};
const number=(n:unknown)=>typeof n==="number"?n.toLocaleString("zh-CN",{maximumFractionDigits:5}):n==null?"暂无":String(n);
const time=(n:unknown)=>typeof n==="number"?new Date(n*1000).toLocaleString("zh-CN"):"暂无";

export function PredictionChallengePanel(){
  const [data,setData]=useState<Row|null>(null);const [report,setReport]=useState<Row|null>(null);const [id,setId]=useState("");
  const [error,setError]=useState("");const [busy,setBusy]=useState(false);const [key,setKey]=useState(()=>crypto.randomUUID());
  const [values,setValues]=useState({name:"100轮预测研究",rounds:100,engine:"ai",capital:100,per_trade:10,shares:20,min_edge:.02,max_loss_pct:30,max_slippage_pct:1,horizon_hours:24,scan_interval_sec:30,use_memory:true,paired_evaluation:false,search:""});
  const load=async()=>{setData(await api("research/challenges"));if(id)setReport(await api("research/challenges?id="+id));};
  useEffect(()=>{
    let active=true;
    const read=async()=>{try{const result=await api("research/challenges");if(active)setData(result);if(id){const detail=await api("research/challenges?id="+id);if(active)setReport(detail);}}catch(e){if(active)setError(e instanceof Error?e.message:"挑战读取失败");}};
    read();const interval=setInterval(read,3000);return()=>{active=false;clearInterval(interval);};
  },[id]);
  const act=async(fn:()=>Promise<unknown>)=>{setBusy(true);setError("");try{await fn();await load();}catch(e){setError(e instanceof Error?e.message:"挑战操作失败");}finally{setBusy(false);}};
  const change=(field:string,value:string|number|boolean)=>{setValues(v=>({...v,[field]:value}));setKey(crypto.randomUUID());};
  const current=report?.challenges.find((c:Row)=>c.id===id);const stats=current?.statistics;
  const create=async()=>{
    const {search,...config}=values;
    const result=await api("research/challenges",{...config,request_id:key,market_query:{provider:"polymarket",lifecycle:"open",upcoming_only:true,limit:50,pages:3,search,slug:""}});
    setId(result.id);setKey(crypto.randomUUID());
  };
  const exportReport=async()=>{
    const full=await api("research/challenges/report?id="+id);
    const url=URL.createObjectURL(new Blob([JSON.stringify(full,null,2)],{type:"application/json"}));
    const link=document.createElement("a");link.href=url;link.download="prediction-challenge-"+id.slice(0,8)+".json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <Panel title="100轮预测挑战" cap="AUTOMATIC REFERENCE PAPER · G1"><div className="pad" data-prediction-challenge>
    <p>独立于24小时规则模板。自动发现公开候选，逐轮预测并等待官方结果；有效SKIP可完成轮次，失败与取消不会凑足目标。资金与成交均为参考模拟。</p>
    <details><summary>创建并启动自动挑战</summary>
      <fieldset disabled={busy} style={{border:0,padding:0,minWidth:0}}><div className="formgrid">
        <Field label="挑战名称"><input aria-label="挑战名称" value={values.name} onChange={e=>change("name",e.target.value)}/></Field>
        <Field label="挑战引擎"><select aria-label="挑战引擎" value={values.engine} onChange={e=>change("engine",e.target.value)}><option value="ai">AI预测</option><option value="rules">规则价格基线（无Key可运行）</option></select></Field>
        {[["目标有效轮次","rounds"],["挑战参考资金","capital"],["每轮最大预算","per_trade"],["目标研究份额","shares"]].map(([title,field])=><Field label={title} key={field}><input aria-label={title} type="number" step="any" value={values[field as keyof typeof values] as number} onChange={e=>change(field,Number(e.target.value))}/></Field>)}
        <Field label="候选标题或slug关键词"><input aria-label="候选关键词" value={values.search} onChange={e=>change("search",e.target.value)}/></Field>
      </div>
      <label><input type="checkbox" checked={values.use_memory} onChange={e=>change("use_memory",e.target.checked)}/>引用本挑战历史记忆（需在Brain开启引用）</label><br/>
      <label><input type="checkbox" checked={values.paired_evaluation} onChange={e=>change("paired_evaluation",e.target.checked)}/>每轮保存有/无记忆配对预测</label>
      <details className="pad"><summary>高级研究与风控参数</summary><div className="formgrid">{[["最低研究优势（0–1）","min_edge"],["累计亏损停机 %","max_loss_pct"],["每轮最大滑点 %","max_slippage_pct"],["候选最晚结束时间（小时内）","horizon_hours"],["公开扫描间隔（秒）","scan_interval_sec"]].map(([title,field])=><Field label={title} key={field}><input aria-label={title} type="number" step="any" value={values[field as keyof typeof values] as number} onChange={e=>change(field,Number(e.target.value))}/></Field>)}</div></details>
      </fieldset>
      <p>每次最多读取3页×50个公开市场，按结束时间筛选样本，每个条件最多安排一次。没有合适市场会等待，不生成假预测。每轮研究官方映射的第一个结果。</p>
      {data?.ai&&<p>当前模型：{data.ai.ready?data.ai.model:"未配置"}；每会话调用上限 {data.ai.calls} 次。AI每轮至少1次预测，配对需2次，自动AI复盘另计；100轮可能超过当前预算，预算不足会暂停。</p>}
      <div className="buttons"><button disabled={busy} onClick={()=>act(create)}>创建并启动预测挑战</button><button onClick={()=>useUI.getState().go("设置")}>打开AI设置</button></div>
    </details>
    <Field label="查看预测挑战"><select aria-label="查看预测挑战" value={id} onChange={e=>{setId(e.target.value);setReport(null);}}><option value="">请选择挑战</option>{data?.challenges.map((c:Row)=><option key={c.id} value={c.id}>{c.config.name} · {labels[c.status]} · {c.id.slice(0,8)}</option>)}</select></Field>
    {current&&stats&&<div data-prediction-progress>
      <p>{labels[current.status]} · {current.config.engine==="ai"?"AI预测":"规则基线"} · 有效完成 {stats.valid_completed} / {current.config.rounds} 轮（{number(100*stats.valid_completed/current.config.rounds)}%）。</p>
      <progress value={stats.valid_completed} max={current.config.rounds} aria-label="挑战有效轮次进度" style={{width:"100%"}}/>
      <p>{current.detail} · 最近统计 {time(current.statistics_as_of)}</p>
      <p>已预测 {stats.predicted} · 参考参与 {stats.participated} · 官方结算 {stats.settled} · 有效SKIP {stats.skipped} · 失败 {stats.failed} · 取消 {stats.cancelled} · 等待结果 {stats.waiting}。</p>
      <p>参考现金 {number(current.account?.cash)} · 待结算持仓成本 {number(stats.open_reference_cost)} · 已退款轮次 {number(stats.refunded)} · 已结算参考收益 {number(current.account?.realized)} · 已预留模型调用 {current.account?.calls??0} 次。</p>
      <p>方向正确率 {stats.accuracy==null?"暂无可评分样本":number(stats.accuracy*100)+"%"}（{stats.accuracy_samples}个二元方向样本） · 参考交易胜率 {stats.trade_win_rate==null?"暂无成交结果":number(stats.trade_win_rate*100)+"%"} · 最长交易连胜/连败 {stats.longest_trade_win_streak}/{stats.longest_trade_loss_streak} · 成本基础最大回撤 {number(stats.max_cost_basis_drawdown_pct)}%。</p>
      <div className="buttons">{[["pause","暂停新轮次"],["resume","恢复挑战"],["stop","结束挑战"]].map(([action,title])=><button key={action} disabled={busy||["COMPLETED","STOPPED","STOPPING","INITIALIZING"].includes(current.status)} onClick={()=>act(()=>api("research/challenges/command",{id,action}))}>{title}</button>)}<button disabled={busy} onClick={()=>act(exportReport)}>导出挑战报告</button></div>
      <p>结束会停止新预测，已有轮次继续等待官方结果。未结算收益不计入已实现收益；回撤口径为现金加持仓成本。通知通道尚待G2验收。</p>
      <Table heads={["轮次 / 市场","状态 / 决策","模型 / 时间","参考成本 / 收益","证据"]} rows={(current.rounds||[]).map((r:Row)=>[
        "#"+r.ordinal+" / "+r.market_id,r.cancelled?"已取消":(labels[r.observed_status]||r.observed_status)+" / "+(({SKIP:"跳过",REFERENCE_BUY:"参考买入"} as Row)[r.receipt.action]||"等待"),
        (r.receipt.model||"等待")+" / "+time(r.receipt.decision_at),number(r.receipt.order?.cost)+" / "+number(r.receipt.realized),
        <div><small>{r.receipt.error}</small>{r.round_id&&<button disabled={busy} onClick={()=>act(async()=>useUI.getState().show({title:"挑战轮次 · "+r.ordinal,summary:"完整源快照、模型、风控与官方结果；参考模拟环境。",data:await api("research/lab/evidence?round_id="+r.round_id)}))}>查看挑战轮次</button>}</div>
      ])}/>
    </div>}
    {(error||data?.error)&&<p role="alert">{error||data?.error}</p>}
    {!data&&error&&<button disabled={busy} onClick={()=>act(()=>api("research/challenges/retry",{}))}>重新连接挑战服务</button>}
    {data?.challenges.length===0&&<p>尚未创建自动预测挑战。</p>}
  </div></Panel>;
}
