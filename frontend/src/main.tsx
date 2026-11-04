import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Curve } from "./equity-chart";
import { BarChart, Bar, ResponsiveContainer, XAxis, Tooltip } from "recharts";
import { motion } from "motion/react";
import {
  LayoutDashboard,
  Radar,
  ListTree,
  Bot,
  Zap,
  Wallet,
  Rows3,
  SlidersHorizontal,
  History,
  Files,
  Bell,
  Settings as Gear,
  SunMoon,
  Activity,
  ChevronRight,
} from "lucide-react";
import { Builder, Settings, Lab } from "./forms";
import {
  Panel,
  Table,
  Modal,
  useUI,
  api,
  qc,
  run,
  txt,
  f,
  time,
  type Row,
} from "./shared";
import "./style.css";
const nav = [
  ["总览", LayoutDashboard],
  ["市场雷达", Radar],
  ["决策中心", ListTree],
  ["自动交易", Bot],
  ["持仓与资产", Wallet],
  ["交易流水", Rows3],
  ["策略实验室", SlidersHorizontal],
  ["历史回测", History],
  ["实验报告", Files],
  ["通知中心", Bell],
  ["设置", Gear],
] as const;
function Events({ rows }: { rows: Row[] }) {
  const show = useUI((s) => s.show);
  return (
    <div className="feed">
      {rows.slice(0, 8).map((r) => (
        <button
          key={r.id}
          onClick={() =>
            show({ ...r, title: r.kind + " · " + (r.symbol || "SYS") })
          }
        >
          <time>{time(r.t)}</time>
          <span>
            <b>
              {r.symbol || "SYS"}　{r.kind}
            </b>
            <small>{r.summary}</small>
          </span>
          <ChevronRight size={13} />
        </button>
      ))}
      {!rows.length && <p className="empty">等待第一条策略事件</p>}
    </div>
  );
}
function RadarTable({ s }: { s: Row }) {
  return (
    <Panel title="候选机会排名" cap="OPPORTUNITY SCORE">
      <Table
        heads={["交易对", "评分", "动量", "相对量能", "RSI", "策略信号"]}
        rows={s.radar.map((m: Row) => [
          <b>{m.symbol} / USDT</b>,
          f(m.score, 1),
          f(m.momentum * 100) + "%",
          f(m.relative) + "×",
          f(m.rsi, 1),
          m.signals?.join("、") || "观望",
        ])}
        click={(i) =>
          useUI
            .getState()
            .show({
              title: s.radar[i].symbol + " · 指标快照",
              data: s.radar[i],
            })
        }
      />
    </Panel>
  );
}
function Positions({ s }: { s: Row }) {
  return (
    <Panel title="策略持仓" cap="POSITION BOOK">
      <Table
        heads={[
          "币种",
          "数量",
          "入场均价",
          "估值价",
          "市值 USDT",
          "未实现盈亏",
        ]}
        rows={Object.entries(s.positions).map(([k, value]) => {
          const p = value as Row;
          return [
            k,
            f(p.qty, 8),
            f(p.entry, 5),
            f(p.price, 5),
            f(p.qty * p.price),
            f(p.qty * p.price - p.cost, 4),
          ];
        })}
      />
    </Panel>
  );
}
function Journal({ id, table }: { id: number; table: string }) {
  const [page, P] = useState(0),
    [symbol, S] = useState(""),
    [kind, K] = useState(""),
    [freeze, F] = useState(false);
  const q = useQuery({
    queryKey: ["journal", id, table, page, symbol, kind],
    queryFn: () =>
      api(
        "journal?id=" +
          id +
          "&table=" +
          table +
          "&page=" +
          page +
          "&symbol=" +
          encodeURIComponent(symbol) +
          "&kind=" +
          kind,
      ),
    refetchInterval: freeze ? false : 2500,
  });
  const a: Row[] = q.data || [];
  return (
    <Panel
      title={
        table === "fills"
          ? "逐笔成交"
          : table === "decisions"
            ? "决策依据"
            : "系统事件"
      }
      cap="AUDIT JOURNAL"
    >
      <div className="buttons pad">
        <input
          placeholder="币种，例如 SOL"
          value={symbol}
          onChange={(e) => {
            S(e.target.value.toUpperCase());
            P(0);
          }}
        />
        <select
          value={kind}
          onChange={(e) => {
            K(e.target.value);
            P(0);
          }}
        >
          {[
            "",
            "BUY",
            "SELL",
            "HOLD",
            "REJECT",
            "AI",
            "ERROR",
            "BREAKER",
            "FILLED",
            "RECONCILE",
          ].map((k) => (
            <option key={k} value={k}>
              {k || "全部类型"}
            </option>
          ))}
        </select>
        <button onClick={() => F(!freeze)}>
          {freeze ? "继续刷新" : "冻结列表"}
        </button>
      </div>
      <Table
        heads={["UTC", "币种", "类型", "依据", "详情"]}
        rows={a
          .slice(0, 30)
          .map((r) => [
            time(r.t),
            r.symbol || "SYS",
            r.kind,
            table === "fills"
              ? f(r.data.price, 5) +
                " × " +
                f(r.data.qty, 6) +
                "　|　费用 " +
                f(r.data.fee, 4) +
                "　|　盈亏 " +
                f(r.data.pnl, 4)
              : r.summary,
            "查看 ↗",
          ])}
        click={(i) =>
          useUI
            .getState()
            .show({ ...a[i], title: "事件 #" + a[i].id + " · " + a[i].kind })
        }
      />
      <div className="buttons pad">
        <button disabled={!page} onClick={() => P(page - 1)}>
          上一页
        </button>{" "}
        {page + 1}{" "}
        <button disabled={a.length < 31} onClick={() => P(page + 1)}>
          下一页
        </button>
      </div>
    </Panel>
  );
}
function Archive({ d }: { d: Row }) {
  const u = useUI();
  return (
    <Panel title="会话对照与报告" cap="SESSION ARCHIVE">
      <Table
        heads={[
          "编号",
          "策略模式",
          "环境",
          "状态",
          "净值 USDT",
          "净收益率",
          "操作",
        ]}
        rows={d.archive.map((r: Row) => [
          r.id,
          txt(r.profile) + " / " + txt(r.engine),
          txt(r.execution),
          txt(r.status),
          f(r.nav, 4),
          f(r.roi) + "%",
          "打开报告 ↗",
        ])}
        click={(i) => {
          u.open(d.archive[i].id);
          u.go("实验报告");
        }}
      />
      {d.report && (
        <div className="pad">
          <div className="performance">
            <ResponsiveContainer width="100%" height={130}>
              <BarChart
                data={Object.entries(d.report.contributions || {}).map(
                  ([symbol, value]) => ({ symbol, value }),
                )}
              >
                <XAxis dataKey="symbol" />
                <Tooltip />
                <Bar dataKey="value" name="净收益贡献 USDT" fill="#9a88ee" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <h3>
            报告 #{d.state.id}　{d.report.pending ? "结算待核对" : "已结算"}
          </h3>
          <p>{d.report.notice}</p>
          <div className="buttons">
            <button
              onClick={() => u.show({ title: "完整报告", data: d.report })}
            >
              统计明细
            </button>
            {["html", "csv", "json"].map((x) => (
              <a key={x} href={"/api/export/" + d.state.id + "/" + x} download>
                {x.toUpperCase()} ↓
              </a>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
function Terminal() {
  const u = useUI(),
    [builder, B] = useState(false),
    [template, setTemplate] = useState(false),
    [theme, T] = useState(localStorage.getItem("terminal-theme") || "dark"),
    [ws, W] = useState(false);
  const q = useQuery({
    queryKey: ["state", u.id],
    queryFn: () => api("state" + (u.id ? "?id=" + u.id : "")),
    refetchInterval: 2500,
  });
  const d = q.data || { archive: [] },
    s = d.state,
    c = s?.config || {};
  useEffect(() => {
    document.body.classList.toggle("light", theme === "light");
    localStorage.setItem("terminal-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (u.msg) {
      const t = setTimeout(() => u.tell(""), 4000);
      return () => clearTimeout(t);
    }
  }, [u.msg]);
  useEffect(() => {
    let closed = false,
      timer: ReturnType<typeof setTimeout>,
      sock: WebSocket;
    function connect() {
      sock = new WebSocket("ws://" + location.host + "/ws");
      sock.onopen = () => W(true);
      let lastEvent=-1;
      sock.onmessage=e=>{const v=JSON.parse(e.data);if(v.event!==lastEvent){lastEvent=v.event;void qc.invalidateQueries({queryKey:['state']})}};
      sock.onclose = () => {
        W(false);
        if (!closed) timer = setTimeout(connect, 3000);
      };
    }
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      sock.close();
    };
  }, []);
  const go = (page: string) => {
    u.go(page);
    B(false);
  };
  const command = (cmd: string) => {
    if (
      ["end", "stop"].includes(cmd) &&
      !window.confirm(
        cmd === "stop"
          ? "立即禁止新订单并保留持仓？"
          : "结束本次会话并生成报告？",
      )
    )
      return;
    const confirmation =
      cmd === "reconcile" && !d.pending?.account_ref
        ? window.prompt("请核对原账户和原单号，确认后输入「核对原账户」") || ""
      : c.execution === "live" && ["start", "resume", "use_rules"].includes(cmd)
        ? window.prompt("确认现货账户与预算。本地止损依赖程序在线。输入「启用实盘」继续") || ""
        : "";
    run(() => api("command", { id: s.id, cmd, confirmation }), "已处理操作");
  };
  const live = s && !["COMPLETED", "STOPPED"].includes(s.lifecycle_status),
    active =
      d.archive.length &&
      !["COMPLETED", "STOPPED"].includes(d.archive[0].status);
  const setup = (challenge: boolean) => {
    go("自动交易");
    setTemplate(challenge);
    if (active) {
      u.open(d.archive[0].id);
      u.tell("已有会话，请先结束当前会话再新建");
    } else B(true);
  };
  const modePage = u.page === "自动交易";
  const render = () => {
    if (q.isError) return <p>本地服务连接失败。请检查后台进程。</p>;
    if (u.page === "设置") return <Settings />;
    if (u.page === "策略实验室") return <Lab onUseTemplate={setup} />;
    if (u.page === "历史回测")
      return (
        <>
          <Panel title="导入分钟行情 CSV" cap="OFFLINE REPLAY">
            <div className="pad">
              <p>
                列名为 symbol, timestamp, open, high, low, close,
                quote_volume。timestamp 为每根收盘时刻的 UTC 秒数，每个币种至少
                76 行。
              </p>
              <input
                aria-label="导入 CSV"
                type="file"
                accept=".csv"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    run(
                      async () =>
                        api("datasets", {
                          name: file.name,
                          text: await file.text(),
                        }),
                      "数据集已校验并保存",
                    );
                }}
              />
              <button onClick={() => setup(false)}>配置历史回放 →</button>
            </div>
          </Panel>
          <Archive d={d} />
        </>
      );
    if (u.page === "实验报告") return <Archive d={d} />;
    if (
      modePage &&
      (builder || !s)
    ) {
      if (active && !builder)
        return (
          <Panel title="已有会话" cap="SESSION">
            <div className="pad">
              <p>一次只调度一个交易会话。请完成当前会话后再创建。</p>
              <button
                onClick={() => {
                  u.open(d.archive[0].id);
                  go("总览");
                }}
              >
                查看当前会话
              </button>
            </div>
          </Panel>
        );
      return (
        <Builder
          key={template ? "challenge" : "normal"}
          challenge={template}
          onCreated={() => {
            B(false);
            go("总览");
          }}
        />
      );
    }
    if (!s)
      return (
        <>
          <section className="welcome">
            <small>OPERATIONS DESK　/　FIRST SESSION</small>
            <h2>建立你的第一个交易会话</h2>
            <p>
              从真实历史行情开始，也可以连接交易所账户。每次开仓前，系统都会记录信号、仓位依据和风控结果。
            </p>
            <div className="buttons">
              <button className="primary" onClick={() => setup(false)}>
                配置普通交易　→
              </button>
              <button onClick={() => go("策略实验室")}>浏览策略模板　↗</button>
            </div>
          </section>
          <div className="tiles">
            {["01　选择数据源", "02　配置资金与引擎", "03　核对风险并启动"].map(
              (n, i) => (
                <div className="panel pad" key={n}>
                  <small>SETUP / 0{i + 1}</small>
                  <h3>{n}</h3>
                </div>
              ),
            )}
          </div>
        </>
      );
    if (u.page === "市场雷达") return <RadarTable s={s} />;
    if (["交易流水", "通知中心", "决策中心"].includes(u.page))
      return (
        <Journal
          key={u.page + s.id}
          id={s.id}
          table={
            u.page === "交易流水"
              ? "fills"
              : u.page === "通知中心"
                ? "system_events"
                : "decisions"
          }
        />
      );
    const metrics = [
      [
        c.execution === "paper" ? "模拟净资产" : "策略归因净值",
        f(d.nav, 3),
        "USDT",
      ],
      ["会话收益率", f((d.nav / c.capital - 1) * 100), "%"],
      ["资金利用率", f(100 * (1 - s.cash / d.nav), 1), "%"],
      [
        "剩余市场时间",
        new Date(Math.max(0, s.deadline - d.now) * 1000)
          .toISOString()
          .slice(11, 19) === "00:00:00" && s.deadline - d.now === 86400
          ? "24:00:00"
          : new Date(Math.max(0, s.deadline - d.now) * 1000)
              .toISOString()
              .slice(11, 19),
        "UTC",
      ],
    ];
    const stats = (
      <div className="metrics">
        {metrics.map(([k, v, n]) => (
          <div key={k}>
            <small>{k}</small>
            <strong>{v}</strong>
            <em>{n}</em>
          </div>
        ))}
      </div>
    );
    if (u.page === "持仓与资产")
      return (
        <>
          {stats}
          <Positions s={s} />
          <Panel title="资产核算" cap="ACCOUNTING">
            <div className="pad">
              现金预算 {f(s.cash, 4)}　已实现 {f(s.realized, 4)}　累计手续费{" "}
              {f(s.fees, 4)}　滑点 {f(s.slippage, 4)}　最大回撤 {f(s.max_dd)}%
            </div>
          </Panel>
        </>
      );
    return (
      <>
        <div className="runbar">
          <span className="badge">{txt(s.lifecycle_status)}</span>
          <b>
            #{String(s.id).padStart(3, "0")}　{txt(c.profile)}
          </b>
          <span>
            {txt(s.engine_override || c.engine)} · {txt(c.execution)} · {txt(c.product)}
          </span>
          <div className="actions">
            {live ? (
              <>
                {s.lifecycle_status === "CREATED" ? (
                  <button className="primary" onClick={() => command("start")}>
                    开始运行
                  </button>
                ) : ["ERROR", "PAUSED", "DATA_STALE"].includes(
                    s.lifecycle_status,
                  ) ? (
                  <button
                    disabled={s.breaker || !!d.pending}
                    onClick={() => command("resume")}
                  >
                    恢复
                  </button>
                ) : (
                  <button onClick={() => command("pause")}>暂停</button>
                )}
                {s.lifecycle_status === "PAUSED" &&
                  c.source !== "public" &&
                  c.engine === "rules" && (
                    <button onClick={() => command("step")}>单步</button>
                  )}
                <button onClick={() => command("end")}>结束</button>
                <button className="warn" onClick={() => command("stop")}>
                  紧急停止
                </button>
              </>
            ) : (
              <button onClick={() => setup(c.profile === "challenge")}>新建会话</button>
            )}
          </div>
        </div>
        {stats}
        {s.ai_status && <div className="status">AI · {s.ai_status}　
          {c.engine === "ai" && !s.engine_override && live && <button onClick={() => command("use_rules")}>手动切回规则</button>}</div>}
        {c.execution !== "paper" && <div className="status">本地策略止损 · 交易所托管保护数量 0　
          {s.local_armed && s.admitted && live ? "本地监控已授权" : "待核验或已停止"}　
          {Object.entries(s.local_watch || {}).filter(([symbol]) => s.positions[symbol]).map(([symbol, raw]) => {
            const w = raw as Row;
            return <p key={symbol}>{symbol} · {w.error || w.waiting || w.trigger || "本地监测"} · 最近检查 {time(w.checked)} UTC</p>;
          })}
          {d.pending && <>原单 {d.pending.client_id} · {d.pending.stage}　
            {d.pending.stage !== "QUEUED" && <button onClick={() => command("reconcile")}>立即核对原单</button>}</>}
          {Object.keys(s.positions).length > 0 && <>　停机后请接管交易所持仓　
            <button onClick={() => {
              if (window.confirm("确认已接管交易所持仓并退出？本地止损将停止。"))
                run(() => api("shutdown", {confirmation:"已接管交易所持仓"}), "正在安全退出");
            }}>接管持仓并退出</button></>}</div>}
        <div className="status">
          {txt(c.source)} · {c.source === "public" ? c.exchange : "历史现货"}
          　/　最近扫描 {time(s.last_scan)}　/　下次 {time(s.next_scan)}
          　/　延迟 {s.delay ?? "—"} 秒　/　{s.latest}
          {["PAUSED","ERROR","DATA_STALE"].includes(s.lifecycle_status)&&<b>　·　估值冻结，以最后有效行情显示</b>}
        </div>
        {c.profile === "challenge" && (
          <div className="challenge-band">
            <Zap size={16} /> 24H DOUBLE CHALLENGE　 距离目标{" "}
            {f(Math.max(0, 2 * c.capital - d.nav), 4)} USDT　 ·　目标收益 +100%
          </div>
        )}
        <div className="charts">
          <Curve d={d} />
          <Panel title="机器决策直播" cap="EVENT FEED">
            <Events rows={d.events} />
          </Panel>
        </div>
        <div className="twocol">
          <RadarTable s={s} />
          <Positions s={s} />
        </div>
        {s.account && (
          <div className="status">
            交易所实际可用 USDT　{f(s.account.free_usdt, 4)}　 /　核验于{" "}
            {time(s.account.checked)} UTC
          </div>
        )}
        <div className="buttons">
          <button onClick={() => go("策略实验室")}>策略模板 ↗</button>
          <button onClick={() => u.show({ title: "会话参数", data: c })}>
            参数快照
          </button>
        </div>
      </>
    );
  };
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <Activity />{" "}
          <div>
            SMART MONEY<small>TRADING TERMINAL</small>
          </div>
        </div>
        <small className="navlabel">WORKSPACE　/　01</small>
        {nav.map(([n, Icon]) => (
          <button
            className={u.page === n ? "active" : ""}
            key={n}
            onClick={() => go(n)}
          >
            <Icon size={16} />
            {n}
          </button>
        ))}
        <footer>
          <i /> 本机工作台 <small>v1.0 BETA</small>
        </footer>
      </aside>
      <main>
        <div className="top">
          <span>SMART MONEY　 /　 OPERATIONS</span>
          <span>
            {ws ? "● 数据通道在线" : "○ 数据通道连接中"}　
            <button
              aria-label="切换主题"
              onClick={() => T(theme === "dark" ? "light" : "dark")}
            >
              <SunMoon size={14} />
            </button>
          </span>
        </div>
        <article>
          <div className="pagehead">
            <div>
              <small>
                VELOCITY TERMINAL　 /　{" "}
                {String(nav.findIndex(([n]) => n === u.page) + 1).padStart(
                  2,
                  "0",
                )}
              </small>
              <h1>{u.page === "总览" ? "交易工作台" : u.page}</h1>
            </div>
            <span className={"env " + (c.execution === "live" ? "warn" : "")}>
              {c.execution ? txt(c.execution) : "尚未创建会话"}
            </span>
          </div>
          <motion.div
            key={u.page}
            initial={{ opacity: 0.5 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.13 }}
            className="content"
          >
            {render()}
          </motion.div>
        </article>
      </main>
      <Modal />
      {u.msg && (
        <div className="toast" role="status">
          {u.msg}
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={qc}>
    <Terminal />
  </QueryClientProvider>,
);
