import React,{useEffect,useState} from "react";
import {Panel,Field,Table,api,useUI,type Row} from "./shared";

const label:Record<string,string>={ACTIVE:"运行中",PAUSED:"已暂停",CLOSED:"已结束",QUEUED:"等待研究",PREDICTING:"预测中",WAITING:"等待官方结果",SETTLED:"已结算",FAILED:"失败 / 未参与",REFERENCE_BUY:"参考模拟买入",SKIP:"跳过",imported:"恢复记录（源待核验）",hypothesis:"待验证假设",observation:"观察",confirmed_result:"已确认本次结果",invalidated:"已失效",reflection:"复盘",PENDING:"等待复盘",RUNNING:"复盘中",COMPLETED:"已完成"};
const show=(value:unknown)=>typeof value==="number"?value.toFixed(5):String(value??"暂无");
const date=(value:unknown)=>typeof value==="number"?new Date(value*1000).toLocaleString("zh-CN"):"暂无";
function download(name:string,data:unknown){
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));
  const link=document.createElement("a");link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export function EventLabPanel(){
  const chosen=useUI(s=>s.researchMarket);
  const [data,setData]=useState<Row|null>(null);const [sid,setSid]=useState("");const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");const [report,setReport]=useState<Row|null>(null);
  const [config,setConfig]=useState({name:"事件参考模拟",capital:100,per_trade:10,max_positions:3,min_edge:.02,max_loss_pct:30,engine:"rules",use_memory:false,paired_evaluation:false});
  const [query,setQuery]=useState({market_id:"",outcome_index:0,shares:10,budget:10,max_slippage_pct:1});
  const [requestKey,setRequestKey]=useState(()=>crypto.randomUUID());
  const [createKey,setCreateKey]=useState(()=>crypto.randomUUID());
  useEffect(()=>{if(chosen){setQuery(q=>({...q,market_id:chosen.market_id,outcome_index:0}));setRequestKey(crypto.randomUUID());}},[chosen]);
  const load=async()=>{const result=await api("research/lab");setData(result);};
  useEffect(()=>{let alive=true;const read=()=>api("research/lab").then(r=>{if(alive)setData(r);}).catch(e=>{if(alive)setError(e.message);});read();const timer=setInterval(read,3000);return()=>{alive=false;clearInterval(timer);};},[]);
  const act=async(fn:()=>Promise<unknown>)=>{setBusy(true);setError("");try{await fn();await load();}catch(e){setError(e instanceof Error?e.message:"研究操作失败");}finally{setBusy(false);}};
  const current=data?.sessions.find((s:Row)=>s.id===sid&&!s.challenge_owner);
  const rounds=data?.rounds.filter((r:Row)=>r.session_id===sid)||[];
  return <><Panel title="事件预测与参考模拟" cap="EVENT PAPER LAB · NO REAL FUNDS">
    <div className="pad" data-event-lab>
      <p>使用真实公开盘口与明确的保守参考成本模型，资金单位为参考USDC。平台实际收费、抵押资产与原生执行单位尚未验收；此处不连接账户，不生成平台订单。</p>
      {data?.gate&&<p>Gate事件适配：待验证、默认禁用。{data.gate.reason}</p>}
      <details><summary>创建独立研究会话</summary>
        <fieldset disabled={busy} style={{border:0,padding:0,minWidth:0}}><div className="formgrid">
          <Field label="研究会话名称"><input aria-label="研究会话名称" value={config.name} onChange={e=>{setConfig({...config,name:e.target.value});setCreateKey(crypto.randomUUID());}}/></Field>
          <Field label="研究决策引擎"><select aria-label="研究决策引擎" value={config.engine} onChange={e=>{setConfig({...config,engine:e.target.value});setCreateKey(crypto.randomUUID());}}><option value="rules">规则价格基线（无优势时SKIP）</option><option value="ai">AI预测（共用已配置服务）</option></select></Field>
          {[["初始参考资金","capital"],["单轮最大预算","per_trade"],["最大研究持仓","max_positions"],["最低研究优势（0–1）","min_edge"],["累计亏损停机 %","max_loss_pct"]].map(([text,key])=><Field key={key} label={text}><input aria-label={text} type="number" step="any" value={config[key as keyof typeof config] as number} onChange={e=>{setConfig({...config,[key]:Number(e.target.value)});setCreateKey(crypto.randomUUID());}}/></Field>)}
        </div>
        <label><input type="checkbox" checked={config.use_memory} onChange={e=>{setConfig({...config,use_memory:e.target.checked});setCreateKey(crypto.randomUUID());}}/>使用同会话的历史记忆（还需开启下方记忆引用）</label><br/>
        <label><input type="checkbox" checked={config.paired_evaluation} onChange={e=>{setConfig({...config,paired_evaluation:e.target.checked});setCreateKey(crypto.randomUUID());}}/>保存有/无记忆的配对预测（AI每轮两次预测调用，另计复盘）</label>
        </fieldset>
        <button disabled={busy} onClick={()=>act(async()=>{const r=await api("research/lab/sessions",{...config,request_id:createKey});setSid(r.id);setCreateKey(crypto.randomUUID());})}>创建参考模拟会话</button>
      </details>
      <Field label="当前研究会话"><select aria-label="当前研究会话" value={sid} onChange={e=>{setSid(e.target.value);setReport(null);setRequestKey(crypto.randomUUID());}}><option value="">请选择研究会话</option>{data?.sessions.filter((s:Row)=>!s.challenge_owner).map((s:Row)=><option key={s.id} value={s.id}>{s.config.name} · {label[s.status]} · {s.id.slice(0,8)}</option>)}</select></Field>
      {current&&<>
        <p>环境：参考模拟 · {label[current.status]} · 可用参考现金 {show(Number(current.cash))} · 已结算参考盈亏 {show(Number(current.realized))} · 已预留AI调用 {current.calls} 次。</p>
        <div className="buttons">{["pause","resume","end"].map((action,i)=><button key={action} disabled={busy||current.status==="CLOSED"} onClick={()=>act(()=>api("research/lab/command",{session_id:sid,action}))}>{["暂停新预测","恢复研究","结束会话"][i]}</button>)}
        <button disabled={busy} onClick={()=>act(async()=>setReport(await api("research/lab/evaluation?session_id="+sid)))}>查看配对评估</button></div>
        <fieldset disabled={busy||current.status!=="ACTIVE"} style={{border:0,padding:0,minWidth:0}}><div className="formgrid">
          <Field label="公开市场（可在上方点击用于预测研究）"><input aria-label="研究市场ID" value={query.market_id} onChange={e=>{setQuery({...query,market_id:e.target.value});setRequestKey(crypto.randomUUID());}}/>{chosen?.market_id===query.market_id&&<small>{chosen?.title}</small>}</Field>
          <Field label="研究结果"><select aria-label="研究结果索引" value={query.outcome_index} onChange={e=>{setQuery({...query,outcome_index:Number(e.target.value)});setRequestKey(crypto.randomUUID());}}><option value="0">{chosen?.market_id===query.market_id?chosen.outcomes[0].name:"第一个结果（按官方映射）"}</option><option value="1">{chosen?.market_id===query.market_id?chosen.outcomes[1].name:"第二个结果（按官方映射）"}</option></select></Field>
          {[["研究目标份额","shares"],["本轮参考预算","budget"],["本轮最大滑点 %","max_slippage_pct"]].map(([text,key])=><Field key={key} label={text}><input aria-label={text} type="number" step="any" value={query[key as keyof typeof query]} onChange={e=>{setQuery({...query,[key]:Number(e.target.value)});setRequestKey(crypto.randomUUID());}}/></Field>)}
        </div><button onClick={()=>act(async()=>{await api("research/lab/rounds",{...query,session_id:sid,request_id:requestKey});setRequestKey(crypto.randomUUID());})}>提交一轮预测研究</button></fieldset>
        <p>规则基线不会把价格当成已校准胜率。AI可以SKIP；独立预算、持仓、时效、费用和亏损检查决定是否形成参考模拟持仓。暂停后已有轮次仍维护官方结果。</p>
        <Table heads={["创建时间 / 市场","状态 / 动作","参考成本 / 盈亏","复盘 / 证据"]} rows={rounds.map((r:Row)=>[
          date(r.created_at)+" / #"+r.inputs.market_id,
          label[r.status]+" / "+(label[r.data.action]??r.data.action??"等待预测"),show(r.data.order?.cost)+" / "+show(r.data.realized),
          <div className="buttons"><button onClick={()=>act(async()=>useUI.getState().show({title:"事件研究轮次 · "+r.id,summary:"模型、完整盘口与规则、引用记忆、风控原因和官方结果留存。参考模拟不代表真实订单。",data:await api("research/lab/evidence?round_id="+r.id)}))}>查看轮次证据</button>{r.status==="SETTLED"&&r.data.reflection_status==="failed"&&<button disabled={busy} onClick={()=>act(()=>api("research/lab/reflection",{round_id:r.id}))}>重试复盘</button>}<small>{r.data.reflection_status==="failed"?"复盘失败，可重试":r.data.error||""}</small></div>
        ])}/>
      </>}
      {report&&<div data-event-evaluation><p>完整配对 {report.paired_rounds} 轮；预测 {report.actual.predicted} / 参与 {report.actual.participated} / 结算 {report.actual.settled} / SKIP {report.actual.skipped} / 失败 {report.actual.failed}。</p>
        <Table heads={["评估项","无记忆","有记忆"]} rows={[["Brier分数（越低越好）","brier"],["Log Loss（越低越好）","log_loss"],["参考净收益","reference_net"],["成本基础最大回撤 %","max_cost_basis_drawdown_pct"],["SKIP比例","skip_ratio"]].map(([name,key])=>[name,show(report.variants.without_memory[key]),show(report.variants.with_memory[key])])}/>
        <p>仅完整配对、可信结算样本参与比较；相同快照与模型、按时间前向引用记忆。收益是独立现金重放的参考模型结果，回撤按现金加持仓成本计算，不是盯市回撤，也未证明模型已校准。</p></div>}
      {(error||data?.error)&&<p role="alert">{error||data?.error}</p>}
      {!data&&error&&<button disabled={busy} onClick={()=>act(()=>api("research/lab/retry",{}))}>重新连接研究服务</button>}
      {!data&&<p>正在读取研究会话…</p>}
    </div>
  </Panel><BrainPanel/></>;
}

function BrainPanel(){
  const [data,setData]=useState<Row|null>(null);const [scope,setScope]=useState("");const [text,setText]=useState("");
  const [error,setError]=useState("");const [busy,setBusy]=useState(false);const [selected,setSelected]=useState<Row|null>(null);const [note,setNote]=useState("");const [invalidate,setInvalidate]=useState(false);
  const load=async()=>setData(await api("brain?scope="+encodeURIComponent(scope)+"&search="+encodeURIComponent(text)));
  useEffect(()=>{load().catch(e=>setError(e.message));},[]);
  const act=async(fn:()=>Promise<unknown>)=>{setBusy(true);setError("");try{await fn();await load();}catch(e){setError(e instanceof Error?e.message:"记忆操作失败");}finally{setBusy(false);}};
  return <Panel title="AI Brain · 模拟学习与长期记忆" cap="TRACEABLE MEMORY · RESEARCH ONLY"><div className="pad" data-brain>
    <p>从模拟决策开始留存观察，结果确认后记录证据与复盘；单次盈利不等于策略有效。AI假设与已确认结果分开保存，记忆不能修改实盘参数。</p>
    {data&&<><div className="buttons" style={{display:"flex",flexWrap:"wrap",gap:18,marginBottom:12}}>{[["enabled","模拟学习写入"],["retrieval","后续决策引用记忆"],["auto_reflect","自动AI复盘"]].map(([key,name])=><label key={key}><input type="checkbox" disabled={busy} checked={data.settings[key]} onChange={e=>{const old=data.settings;const next={...old,[key]:e.target.checked};setData({...data,settings:next});act(async()=>{try{await api("brain/settings",next);}catch(err){setData(p=>p?{...p,settings:old}:p);throw err;}});}}/>{name}</label>)}</div>
      <p>已记录 {data.total} 条 · {data.settings.enabled?"学习开启":"学习已暂停"} · {data.settings.retrieval?"引用开启":"引用关闭"}。模型切换后记忆保留；作用域隔离不同会话、平台和执行环境。</p>
      <div className="formgrid"><Field label="记忆来源"><select aria-label="记忆来源" value={scope} onChange={e=>setScope(e.target.value)}><option value="">全部来源</option>{data.scopes.map((s:string)=><option key={s} value={s}>{s.startsWith("event:")?"事件研究会话 "+s.slice(6,14):s.replace("spot:","现货模拟 · ")}</option>)}</select></Field>
      <Field label="搜索记忆内容"><input aria-label="搜索记忆内容" value={text} onChange={e=>setText(e.target.value)}/></Field></div>
      <div className="buttons"><button disabled={busy} onClick={()=>act(load)}>搜索 / 刷新记忆</button><button disabled={busy} onClick={()=>act(async()=>download("smart-money-brain.json",await api("brain/export")))}>导出记忆备份</button>
      <label>恢复记忆备份 <input aria-label="恢复记忆备份" type="file" accept=".json" disabled={busy} onChange={e=>{const file=e.target.files?.[0];if(file)act(async()=>{if(file.size>8000000)throw Error("备份不能超过8MB");await api("brain/restore",JSON.parse(await file.text()));});e.target.value="";}}/></label></div>
      <Table heads={["来源 / 类型","状态 / 版本","可用时间","证据与纠错"]} rows={data.rows.map((m:Row)=>[
        (m.scope.startsWith("event:")?"事件会话 "+m.scope.slice(6,14):m.scope.replace("spot:","现货模拟 · "))+" / "+(label[m.kind]||m.kind),(label[m.status]||m.status)+" / v"+m.revision,date(m.available_at),
        <div className="buttons"><button onClick={()=>useUI.getState().show({title:"Brain记忆 · "+m.id,summary:"保留源记录、模型和证据；假设不等于已验证规律。",data:m})}>查看记忆来源</button><button onClick={()=>{setSelected(m);setNote("");setInvalidate(false);}}>纠错 / 标记失效</button></div>
      ])}/>
      {selected&&<section className="panel pad"><p>纠错 v{selected.revision} · {selected.id.slice(0,12)}；原版本保留，历史预测不会看到未来修订。</p><Field label="纠错说明"><textarea aria-label="纠错说明" value={note} onChange={e=>setNote(e.target.value)}/></Field>
        <label><input type="checkbox" checked={invalidate} onChange={e=>setInvalidate(e.target.checked)}/>停止后续引用此条记忆</label><div className="buttons"><button disabled={busy||!note.trim()} onClick={()=>act(async()=>{await api("brain/correct",{memory_id:selected.id,expected_revision:selected.revision,note,invalidate});setSelected(null);})}>保存记忆纠错</button><button onClick={()=>setSelected(null)}>取消</button></div></section>}
      {data.rows.length===0&&<p>暂无匹配记忆；运行模拟后可刷新查看。</p>}
      {data.reflection_jobs.length>0&&<details><summary>现货模拟AI复盘任务（最近20条）</summary><Table heads={["来源","状态","诊断 / 操作"]} rows={data.reflection_jobs.map((j:Row)=>[j.scope,label[j.status]||j.status,<div>{j.error}{j.status==="FAILED"&&<button disabled={busy} onClick={()=>act(()=>api("brain/retry",{memory_id:j.id}))}>重试AI复盘</button>}</div>])}/><p>自动复盘使用独立通道和已配置模型，另设每日调用上限（沿用当前AI调用预算值）；缺少模型保持等待，失败不会影响持仓和保护。</p></details>}
    </>}
    {(error||data?.error)&&<p role="alert">{error||data?.error}</p>}
  </div></Panel>;
}
