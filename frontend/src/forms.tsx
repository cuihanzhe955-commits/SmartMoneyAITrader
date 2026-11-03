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

function LiveChecks() {
  const [busy, setBusy] = useState(false), [result, setResult] = useState<Row | null>(null);
  const session = useQuery({queryKey: ["acceptance-session"], queryFn: () => api("state")});
  const id = session.data?.state?.id;
  const saved = useQuery({queryKey: ["acceptance-report", id],
    queryFn: () => api("account/verification?id=" + id), enabled: !!id});
  const report = result?.session_id === id ? result : saved.data?.report;
  const remote = session.data?.state?.config?.execution !== "paper" && !!id;
  return <Panel title="实盘验收 · 只读健康检查" cap="LIVE READINESS">
    <div className="pad">
      <p>核验账户权限、专用预算、现货规则、盘口时效及未核对订单。检查不会下单、启动机器人或赋予交易授权。</p>
      <p>{id ? "当前会话 #" + id + " · " + txt(session.data.state.config.execution) : "尚未创建会话"} · 托管保护单尚未验收</p>
      {!remote && <p>请先在自动交易页创建交易所现货会话；创建后保持未启动也可以检查。本地模拟不能作为实盘验收。</p>}
      <div className="buttons">
        <button disabled={!remote || busy} onClick={async () => {
          setBusy(true);
          try { await run(async () => setResult(await api("account/verify", {id})), "只读检查完成"); }
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
        <p role="status">{report.status === "READ_ONLY_PASSED" ? "只读检查通过 · 尚未完成实盘验收" : "存在阻断项 · 请先处理"} · {new Date(report.finished_at * 1000).toLocaleString("zh-CN")}</p>
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
