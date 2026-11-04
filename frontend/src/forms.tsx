import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Field, Panel, api, run, useUI, txt, Row } from "./shared";
const strategies = [
  "动量突破",
  "趋势跟随",
  "均值回归",
  "成交量异常",
  "波动率策略",
];
function select(v: string, set: (x: string) => void, items: string[]) {
  return (
    <select value={v} onChange={(e) => set(e.target.value)}>
      {items.map((x) => (
        <option key={x} value={x}>
          {txt(x)}
        </option>
      ))}
    </select>
  );
}
export function Builder({
  challenge,
  onCreated,
}: {
  challenge: boolean;
  onCreated: () => void;
}) {
  const [template, setTemplate] = useState(challenge ? "challenge" : "normal");
  return <>
    <Panel title="创建会话 · 选择策略模板" cap="STRATEGY TEMPLATE">
      <div className="pad">
        <Field label="策略模板">
          <select aria-label="策略模板" value={template} onChange={(e) => setTemplate(e.target.value)}>
            <option value="normal">普通自主交易</option>
            <option value="challenge">24小时翻倍挑战</option>
          </select>
        </Field>
        <small>切换模板会重置当前未提交的表单，并恢复本地模拟环境。选择模板仅填写草稿，创建后仍需单独启动。</small>
      </div>
    </Panel>
    <SessionBuilder key={template} challenge={template === "challenge"} onCreated={onCreated} />
  </>;
}

function SessionBuilder({
  challenge,
  onCreated,
}: {
  challenge: boolean;
  onCreated: () => void;
}) {
  const preset =
    JSON.parse(localStorage.getItem("strategy-preset") || "null") || strategies;
  const [s, set] = useState<Row>({
    profile: challenge ? "challenge" : "normal",
    execution: "paper",
    source: "history",
    engine: "rules",
    product: "spot",
    exchange: "okx",
    capital: challenge ? 10 : 1000,
    speed: 120,
    leverage: 1,
    target: challenge ? 25 : 12,
    risk_per_trade_pct: 1,
    candidates: 20,
    breaker: challenge ? 35 : 12,
    loss_limit: challenge ? 35 : 12,
    decision_interval: 60,
    strict_min: 1,
    interval: 15,
    slots: challenge ? 3 : 4,
    utilization: challenge ? 90 : 60,
    concentration: challenge ? 45 : 20,
    stop: challenge ? 2.5 : 2,
    profit: challenge ? 5 : 4,
    trail: 2,
    cooldown: challenge ? 60 : 180,
    fee: 0.1,
    frame: 1,
    trend: 5,
    settlement: "mark",
    strategies: preset,
    consent: false,
    confirmation: "",
    dataset: "",
  });
  const upd = (k: string, v: unknown) => set((p) => ({ ...p, [k]: v }));
  const ds = useQuery({
    queryKey: ["datasets"],
    queryFn: () => api("datasets"),
  });
  const parameters = useQuery({queryKey: ["parameters"], queryFn: () => api("parameters")});
  const warnings = Object.entries(parameters.data || {}).filter(([key, value]) => {
    const bounds = value as Row;
    return typeof s[key] === "number" && (s[key] < bounds.low || s[key] > bounds.high);
  });
  const note = (key: string) => {
    const bounds = parameters.data?.[key];
    return bounds && <small>推荐 {bounds.low}–{bounds.high}；有效值可超出推荐范围</small>;
  };
  return (
    <form
      className="builder"
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const r = await api("sessions", s);
          useUI.getState().open(r.id);
          onCreated();
        }, "会话已创建，请核对配置后启动");
      }}
    >
      <div className="formhead">
        <small>
          SESSION BUILDER　/　{challenge ? "CHALLENGE" : "STANDARD"}
        </small>
        <h2>{challenge ? "创建 24 小时翻倍挑战" : "配置自主交易会话"}</h2>
        <p>
          {challenge
            ? "以 +100% 为实验目标，由规则引擎决策。选择真实账户后，成交直接作用于交易所资产。"
            : "选择行情、执行环境与决策引擎。无密钥也可使用离线规则模式。"}
        </p>
      </div>
      <div className="formgrid">
        <Field label="01 · 执行环境">
          {select(
            s.execution,
            (v) =>
              set((p) => ({
                ...p,
                execution: v,
                product: v === "live" ? "spot" : p.product,
                source: v === "paper" ? p.source : "public",
                settlement: "mark",
              })),
            ["paper", "demo", "live"],
          )}
        </Field>
        <Field label="行情来源">
          {select(
            s.source,
            (v) =>
              set((p) => ({
                ...p,
                source: v,
                product: v === "public" ? p.product : "spot",
              })),
            s.execution === "paper" ? ["history", "csv", "public"] : ["public"],
          )}
        </Field>
        {s.source === "csv" && (
          <Field label="数据集">
            <select
              required
              value={s.dataset}
              onChange={(e) => upd("dataset", e.target.value)}
            >
              <option value="">请选择 CSV 归档</option>
              {ds.data?.map((d: Row) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        {s.source === "public" && (
          <>
            <Field label="交易所">
              {select(s.exchange, (v) => upd("exchange", v), [
                "okx",
                "binance",
              ])}
            </Field>
            <Field label="账户产品">
              {select(s.product, (v) => upd("product", v), s.execution === "live" ? ["spot"] : ["spot", "swap"])}
            </Field>
          </>
        )}
        <Field
          label={
            s.execution === "paper"
              ? "初始模拟本金 · USDT"
              : "策略名义资金预算 · USDT"
          }
        >
          <input
            type="number"
            min="0"
            step="any"
            required
            value={s.capital}
            onChange={(e) => upd("capital", +e.target.value)}
          />
        </Field>
        <Field label="02 · 决策引擎">
          {select(s.engine, (v) => upd("engine", v), challenge ? ["rules"] : ["rules", "ai"])}
        </Field>
        {s.source !== "public" && (
          <Field label="历史市场回放倍率">
            <select
              value={s.speed}
              onChange={(e) => upd("speed", +e.target.value)}
            >
              {[1, 5, 20, 100, 120, 600, 3600].map((n) => (
                <option value={n} key={n}>
                  {n}×
                </option>
              ))}
            </select>
          </Field>
        )}
        {s.product === "swap" && (
          <Field label="账户已设置的逐仓杠杆">
            <input
              type="number"
              min="1"
              max="5"
              value={s.leverage}
              onChange={(e) => upd("leverage", +e.target.value)}
            />
          </Field>
        )}
        <Field label="单笔目标 / 净资产 %">
          <input
            aria-label="单笔目标 / 净资产 %"
            type="number"
            min="0"
            max="100"
            step="any"
            required
            value={s.target}
            onChange={(e) => upd("target", +e.target.value)}
          />
          {note("target")}
        </Field>
        <Field label="单笔风险预算 / 净资产 %">
          <input aria-label="单笔风险预算 / 净资产 %" type="number" required min="0" max="100" step="any"
            value={s.risk_per_trade_pct}
            onChange={(e) => upd("risk_per_trade_pct", +e.target.value)} />
          {note("risk_per_trade_pct")}
          <small>按止损、双边费用与滑点计算入场金额。旧配置缺省为 1%。</small>
        </Field>
        <Field label="回撤熔断 / 峰值净资产 %">
          <input
            aria-label="回撤熔断 / 峰值净资产 %"
            type="number"
            min="0"
            max="100"
            step="any"
            value={s.breaker}
            onChange={(e) => upd("breaker", +e.target.value)}
          />
          {note("breaker")}
        </Field>
      </div>
      <details>
        <summary>策略与执行参数</summary>
        <div className="chips">
          {strategies.map((n) => (
            <label key={n}>
              <input
                type="checkbox"
                checked={s.strategies.includes(n)}
                onChange={(e) =>
                  upd(
                    "strategies",
                    e.target.checked
                      ? [...s.strategies, n]
                      : s.strategies.filter((a: string) => a !== n),
                  )
                }
              />
              {n}
            </label>
          ))}
        </div>
        <div className="formgrid">
          {[
            ["累计亏损上限 %", "loss_limit"],
            ["决策间隔（秒）", "decision_interval"],
            ["最小名义金额 USDT", "strict_min"],
            ["扫描间隔（秒）", "interval"],
            ["候选数量（当前数据池仍为 8 币）", "candidates"],
            ["持仓数上限", "slots"],
            ["利用率 / 净资产 %", "utilization"],
            ["单币上限 / 净资产 %", "concentration"],
            ["止损 / 入场价 %", "stop"],
            ["止盈 / 入场价 %", "profit"],
            ["移动回撤 / 最高价 %", "trail"],
            ["开仓冷却（秒）", "cooldown"],
            ["估算费率 / 成交额 %", "fee"],
            ["主决策回看周期（分钟）", "frame"],
            ["高级趋势回看周期（分钟）", "trend"],
          ].map(([label, k]) => (
            <Field key={k} label={label}>
              <input
                aria-label={label}
                type="number"
                step="any"
                value={s[k]}
                onChange={(e) => upd(k, +e.target.value)}
              />
              {note(k)}
            </Field>
          ))}
          {s.execution === "paper" && (
            <Field label="结束结算">
              <select
                value={s.settlement}
                onChange={(e) => upd("settlement", e.target.value)}
              >
                <option value="mark">按最后有效价格估值</option>
                <option value="close">尝试模拟平仓</option>
              </select>
            </Field>
          )}
        </div>
      </details>
      {warnings.length > 0 && <div className="pad" role="status">
        <b>超出推荐范围，保留你的选择</b>
        <ul>{warnings.map(([key, value]) => {
          const b = value as Row;
          return <li key={key}>{b.name} 当前 {s[key]}，推荐 {b.low}–{b.high}</li>;
        })}</ul>
      </div>}
      {s.execution === "live" && (
        <Field label="真实资金确认 · 输入「启用实盘」">
          <input
            required
            value={s.confirmation}
            onChange={(e) => upd("confirmation", e.target.value)}
          />
        </Field>
      )}
      {s.execution === "paper" && (
        <div className="pad">
          <Field label="模拟成交规则">
            <select
              value={s.paper_rules || "micro"}
              onChange={(e) => upd("paper_rules", e.target.value)}
            >
              <option value="micro">微资金碎片撮合</option>
              <option value="venue">严格数量与精度 · OKX 现货归档快照</option>
            </select>
          </Field>
          <small>
            模拟委托至少等待一根有效分钟线。微资金成交可能不满足交易所实际规则。
          </small>
        </div>
      )}
      <div className="foot">
        <label>
          <input
            type="checkbox"
            required
            checked={s.consent}
            onChange={(e) => upd("consent", e.target.checked)}
          />{" "}
          已确认账户、策略及亏损风险
        </label>
        <button className="primary">创建会话 →</button>
      </div>
    </form>
  );
}
export function Settings() {
  const q = useQuery({
    queryKey: ["settings"],
    queryFn: () => api("settings"),
  });
  return q.data ? <><LiveChecks /><Config data={q.data} /></> : <p>读取配置…</p>;
}

function protectionNumber(value: any) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) return "未知";
  return Number(value).toLocaleString("zh-CN", { maximumSignificantDigits: 12 });
}

function ProtectionDetails({ order }: { order: any }) {
  const [open, setOpen] = useState(false);
  const [before, setBefore] = useState(0);
  const query = useQuery({queryKey: ["protection-report", order.client_id, before], enabled: open, refetchInterval: open ? 5000 : false,
    queryFn: () => api("protection-report?id=" + order.session_id + "&client_id=" + encodeURIComponent(order.client_id) + "&before=" + before)});
  const report = query.data;
  return <div>
    <button aria-expanded={open} onClick={() => setOpen(!open)}>核对时间线</button>
    {open && <div aria-label="保护单核对时间线" style={{maxWidth: 420, whiteSpace: "normal", overflowWrap: "anywhere"}}>
      {query.isPending ? <p>正在读取本机记录…</p> : query.isError ? <p>时间线读取失败，请重新查询</p> : <>
        <p>{report.guidance}</p>
        <p>{report.evidence_scope}</p>
        <p>界面数值适度舍入；导出报告保留原始数值。</p>
        {report.children?.map((child: any, i: number) => <p key={i}>
          子订单 {i+1} · {child.stage} · {child.receipt
            ? "已核对成交量 " + protectionNumber(child.receipt.qty) + "，成交金额 " + protectionNumber(child.receipt.nominal) + " USDT，手续费折算 " + protectionNumber(child.receipt.fee) + " USDT，已实现盈亏 " + protectionNumber(child.receipt.pnl) + " USDT"
            : "尚无可核验成交，不计作已成交"}
        </p>)}
        {report.children_truncated && <p>子订单明细超过本页上限，请分批核对；此页不代表完整清单。</p>}
        <ol>{report.events.map((e: any) => <li key={e.id}>
          {e.recorded_at ? new Date(e.recorded_at * 1000).toLocaleString() : "历史记录时间未保存"} · {e.label}
          {" · 数量 " + protectionNumber(e.quantity) + " · 触发价 " + protectionNumber(e.stop_price)}
          {e.remaining_quantity != null && " · 剩余 " + protectionNumber(e.remaining_quantity)}
          {e.cancel_attempts > 0 && " · 撤销提交 " + e.cancel_attempts + "/3"}
          {e.released && " · 已核对释放"}
          {e.maintenance_failed && " · 维护未确认"}
        </li>)}</ol>
        <div className="buttons">
          {report.has_more && <button onClick={() => setBefore(report.next_before)}>更早记录</button>}
          {before > 0 && <button onClick={() => setBefore(0)}>最近记录</button>}
          <button onClick={() => query.refetch()}>刷新时间线</button>
          <button onClick={() => {
            const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type:"application/json"}));
            const link = document.createElement("a"); link.href = url; link.download = "protection-page-" + order.client_id + ".json"; link.click(); URL.revokeObjectURL(url);
          }}>导出本页核对报告</button>
        </div>
      </>}
    </div>}
  </div>;
}

function LiveChecks() {
  const [busy, setBusy] = useState(false);
  const [stopSymbol, setStopSymbol] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [protectionBusy, setProtectionBusy] = useState(false);
  const protection = useQuery({queryKey: ["protection-status"], queryFn: () => api("protection-status"), refetchInterval: 5000});
  const session = useQuery({queryKey: ["acceptance-session"], queryFn: () => api("state")});
  const id = session.data?.state?.id;
  const saved = useQuery({queryKey: ["acceptance-report", id],
    queryFn: () => api("account/verification?id=" + id), enabled: !!id, refetchInterval: 5000});
  const report = saved.data?.report;
  const remote = session.data?.state?.config?.execution !== "paper" && !!id;
  const demo = session.data?.state?.config?.execution === "demo" && session.data?.state?.config?.exchange === "okx" && session.data?.state?.config?.product === "spot";
  const holdings = Object.keys(session.data?.state?.positions || {});
  const protect = async (action: string, client_id = "", session_id = id) => {
    setProtectionBusy(true);
    try { await run(async () => {
      await api("protection-action", {id: session_id, action, client_id,
        symbol: stopSymbol || holdings[0] || "", stop_price: action === "create" ? Number(stopPrice) : null});
      await protection.refetch(); await session.refetch();
    }, "模拟保护操作已处理，请核对状态"); }
    finally { setProtectionBusy(false); }
  };
  return <Panel title="实盘验收 · 只读健康检查" cap="LIVE READINESS">
    <div className="pad">
      <p>核验账户权限、专用预算、现货规则、盘口时效及未核对订单。检查不会下单、启动机器人或赋予交易授权。</p>
      <div aria-label="托管保护维护状态">
        <strong>托管保护维护</strong>
        {protection.isPending ? <p>正在读取维护状态…</p> : protection.isError ? <p>维护状态读取失败，请检查本地服务</p> : <>
          <p>{protection.data?.running ? "恢复维护运行中" : "恢复维护未运行"} · 仅 OKX 模拟环境恢复；自动创建未开启</p>
          {demo && <div className="buttons">
            <select aria-label="模拟保护持仓" value={stopSymbol || holdings[0] || ""} onChange={e => setStopSymbol(e.target.value)}><option value="" disabled>选择实际持仓</option>{holdings.map(k => <option key={k}>{k}</option>)}</select>
            <input aria-label="模拟保护止损价" type="number" min="0" step="any" placeholder="止损触发价" value={stopPrice} onChange={e => setStopPrice(e.target.value)} />
            <button disabled={protectionBusy || !holdings.length || !Number.isFinite(Number(stopPrice)) || Number(stopPrice) <= 0 || protection.data?.blocks_orders} onClick={() => protect("create")}>创建模拟保护</button>
          </div>}
          {protection.data?.error && <p>{protection.data.error}</p>}
          {protection.data?.blocks_orders && <p>保护单待核对，普通委托和账户切换已阻断</p>}
          {protection.data?.review_required && <p>保护交接后普通交易保持暂停，恢复前必须重新验收。</p>}
          {protection.data?.handover?.map((p: any) => <p key={p.symbol}>待接管持仓：{p.symbol} · 剩余数量 {protectionNumber(p.quantity)}。可为实际剩余持仓创建下一代模拟保护。</p>)}
          {!protection.data?.orders?.length ? <p>暂无托管保护记录；当前不代表已获得交易所保护</p> :
            <table className="protection-table"><thead><tr><th>币种</th><th>实际记录状态</th><th>原保护数量</th><th>核对结果与剩余持仓</th><th>模拟操作</th></tr></thead><tbody>
              {protection.data.orders.map((o: any) => <tr key={o.client_id}><td>{o.symbol}</td><td>{o.released ? "核对完成 · 已释放" : ({PLANNED:"待发送",SENDING:"提交待确认",UNKNOWN:"状态未知",ACCEPTED:"请求已受理",LIVE:"待触发记录",CANCEL_PENDING:"撤销待确认",TRIGGERED:"已触发 · 待验收",CANCELED:"已取消",FAILED:"触发失败"} as Record<string,string>)[o.stage] || o.stage}</td><td>{protectionNumber(o.quantity)}</td><td>{o.remaining_quantity != null && <div>成交核对后剩余 {protectionNumber(o.remaining_quantity)}</div>}{o.needs_attention && <strong>需要处理 · </strong>}{o.maintenance_error || (o.stale ? "记录已过期，请重新查原单" : o.released ? "账户已核对，恢复交易前重新验收" : o.children_reconciled ? "子订单已核对，账户仍需验收" : "等待核对")}</td><td>{!o.released && <>
                {(o.cancel_attempts || 0) > 0 && <small>撤销提交 {o.cancel_attempts}/3 次 · 重试前查询原单</small>}<button disabled={protectionBusy || o.stage === "PLANNED"} onClick={() => protect("query", o.client_id, o.session_id)}>查询原单</button>
                {["PLANNED", "LIVE", "CANCEL_PENDING"].includes(o.stage) && <button disabled={protectionBusy || (o.cancel_attempts || 0) >= 3 || (o.cancel_retry_after || 0) > Date.now()/1000} onClick={() => protect("cancel", o.client_id, o.session_id)}>{o.stage === "CANCEL_PENDING" ? "查单后重试撤销" : "撤销模拟保护"}</button>}
                {(["CANCELED", "FAILED"].includes(o.stage) || o.children_reconciled) && <button disabled={protectionBusy} onClick={() => protect("finalize", o.client_id, o.session_id)}>核对账户并释放</button>}
              </>}<ProtectionDetails order={o} /></td></tr>)}
            </tbody></table>}
        </>}
      </div>
      <p>{id ? "当前会话 #" + id + " · " + txt(session.data.state.config.execution) : "尚未创建会话"} · 托管保护单尚未验收</p>
      {!remote && <p>请先在自动交易页创建交易所现货会话；创建后保持未启动也可以检查。本地模拟不能作为实盘验收。</p>}
      <div className="buttons">
        <button disabled={!remote || busy} onClick={async () => {
          setBusy(true);
          try { await run(async () => { await api("account/verify", {id}); await saved.refetch(); }, "只读检查完成"); }
          finally { setBusy(false); }
        }}>{busy ? "正在核验…" : "运行只读验收"}</button>
        {report && <button onClick={() => {
          const link = document.createElement("a"), url = URL.createObjectURL(
            new Blob([JSON.stringify(report, null, 2)], {type:"application/json"}));
          link.href = url; link.download = "local-acceptance-" + report.id + ".json"; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }}>导出本机检查报告</button>}
      </div>
      {report && <>
        <p role="status">{report.requires_recheck ? "旧验收报告 · 需要重新核验" : report.status === "READ_ONLY_PASSED" ? "只读检查通过 · 尚未完成实盘验收" : "存在阻断项 · 请先处理"} · {new Date(report.finished_at * 1000).toLocaleString("zh-CN")}</p>
        {report.requires_recheck && <p>{report.recheck_reasons.join("；")}</p>}
        <p>结果为当时快照，账户或持仓变化后请重新检查；启动时仍会独立复核。</p>
        <div className="scroll"><table><thead><tr><th>检查项</th><th>结果</th><th>说明</th></tr></thead>
          <tbody>{report.checks.map((c: Row, i: number) => <tr key={c.key + i}>
            <td>{c.name}</td><td>{({PASS:"通过",FAIL:"阻断",WARN:"提醒"} as Row)[c.status]}</td>
            <td>{c.message}{c.key === "protection" && "；交易所托管保护未验证"}
              {c.details && <button onClick={() => useUI.getState().show({title:c.name, data:c.details})}>查看明细</button>}
            </td></tr>)}</tbody></table></div>
        <p>{report.remaining.join("；")}</p>
      </>}
    </div>
  </Panel>;
}
function Config({ data }: { data: Row }) {
  const [a, A] = useState<Row>(data.ai),
    [aiKey, AK] = useState(""),
    [venue, V] = useState("okx"),
    [env, E] = useState("demo"),
    [product, P] = useState("spot"),
    [key, K] = useState(""),
    [secret, S] = useState(""),
    [pass, H] = useState("");
  return (
    <div className="twocol">
      <Panel title="交易所账户" cap="EXCHANGE VAULT">
        <div className="pad">
          <p>
            密钥由 Windows DPAPI 绑定当前用户加密保存。测试按钮只读取可用余额。
          </p>
          <div className="formgrid">
            <Field label="全球站">{select(venue, V, ["okx", "binance"])}</Field>
            <Field label="凭据环境">{select(env, E, ["demo", "live"])}</Field>
          </div>
          {[
            ["API Key", key, K],
            ["Secret", secret, S],
            ...(venue === "okx" ? [["Passphrase", pass, H]] : []),
          ].map(([n, v, fn]) => (
            <Field key={String(n)} label={String(n)}>
              <input
                type="password"
                autoComplete="new-password"
                value={String(v)}
                onChange={(e) => (fn as (s: string) => void)(e.target.value)}
              />
            </Field>
          ))}
          <div className="buttons">
            <button
              onClick={() =>
                run(async () => {
                  await api("credentials", {
                    exchange: venue,
                    environment: env,
                    key,
                    secret,
                    passphrase: pass,
                  });
                  K("");
                  S("");
                  H("");
                })
              }
            >
              加密保存
            </button>
            {select(product, P, ["spot", "swap"])}
            <button
              onClick={() =>
                run(async () => {
                  const r = await api("account/test", {
                    exchange: venue,
                    execution: env,
                    product,
                  });
                  useUI.getState().show({ title: "账户连接成功", data: r });
                }, "只读核验完成")
              }
            >
              检查余额
            </button>
          </div>
          <p>已配置　{data.accounts.join("、") || "无"}</p>
        </div>
      </Panel>
      <Panel title="AI 军师与交易员" cap="PROVIDER">
        <div className="pad">
          <p>
            使用兼容 Chat Completions 的服务。每轮先分析市场，再校验结构化提案。
          </p>
          {[
            ["服务地址", "base"],
            ["模型", "model"],
            ["超时秒数", "timeout"],
            ["调用间隔秒数", "interval"],
            ["每个会话调用预算（次数）", "calls"],
          ].map(([label, k]) => (
            <Field key={k} label={label}>
              <input
                value={a[k]}
                onChange={(e) =>
                  A({
                    ...a,
                    [k]:
                      typeof a[k] === "number"
                        ? +e.target.value
                        : e.target.value,
                  })
                }
              />
            </Field>
          ))}
          <Field label="服务密钥">
            <input
              type="password"
              value={aiKey}
              placeholder={data.ai_ready ? "已加密保存" : "输入 API Key"}
              onChange={(e) => AK(e.target.value)}
            />
          </Field>
          <Field label="故障策略">
            <select
              value={a.fallback}
              onChange={(e) => A({ ...a, fallback: e.target.value })}
            >
              <option value="rules">回退规则</option>
              <option value="hold">暂停开仓</option>
              <option value="manual">等待人工切回规则</option>
            </select>
          </Field>
          <div className="buttons">
            <button
              onClick={() =>
                run(async () => {
                  await api("ai", { config: a, key: aiKey });
                  AK("");
                })
              }
            >
              保存 AI 配置
            </button>
            <button
              onClick={() => run(() => api("ai/test", {}), "AI 连接成功")}
            >
              测试连接
            </button>
          </div>
        </div>
      </Panel>
    </div>
  );
}
export function Lab({ onUseTemplate }: { onUseTemplate: (challenge: boolean) => void }) {
  const [v, set] = useState<string[]>(
    JSON.parse(localStorage.getItem("strategy-preset") || "null") || strategies,
  );
  return (
    <>
    <Panel title="策略模板" cap="SESSION TEMPLATES">
      <div className="pad">
        <p>选择模板后在自动交易页核对资金、环境和风险参数。已有会话和报告保持独立。</p>
        <div className="twocol">
          <section className="panel pad">
            <h3>普通自主交易</h3>
            <p>规则引擎或 AI 增强，按自己的资金预算与风控配置运行。</p>
            <button onClick={() => onUseTemplate(false)}>使用普通模板</button>
          </section>
          <section className="panel pad">
            <h3>24小时翻倍挑战</h3>
            <p>纯规则的 24 小时交易实验，默认目标 +100%。目标不保证实现，也不提高交易权限。</p>
            <p>倒计时、净值进度、持仓和决策在自动交易工作台查看，结算后生成独立报告。</p>
            <button onClick={() => onUseTemplate(true)}>使用挑战模板</button>
          </section>
        </div>
      </div>
    </Panel>
    <Panel title="组合策略预设" cap="STRATEGY MIX">
      <div className="pad">
        <p>
          选择下一次新建实验要启用的信号。普通模式按共振信号筛选，挑战叠加短周期动量门槛。
        </p>
        {strategies.map((n, i) => (
          <label className="strategy" key={n}>
            <b>0{i + 1}</b>
            <span>
              {n}
              <small>
                {
                  [
                    "价格突破近期高点，短线动量为正",
                    "快慢 EMA 与趋势方向一致",
                    "低 RSI 后出现向上修复",
                    "相对成交量放大并伴随上涨",
                    "ATR 扩张与动量同步",
                  ][i]
                }
              </small>
            </span>
            <input
              type="checkbox"
              checked={v.includes(n)}
              onChange={(e) =>
                set(e.target.checked ? [...v, n] : v.filter((x) => x !== n))
              }
            />
          </label>
        ))}
        <button
          disabled={!v.length}
          onClick={() => {
            localStorage.setItem("strategy-preset", JSON.stringify(v));
            useUI.getState().tell("新会话策略预设已保存");
          }}
        >
          保存预设
        </button>
      </div>
    </Panel>
    </>
  );
}
