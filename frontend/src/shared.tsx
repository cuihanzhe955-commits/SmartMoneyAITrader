import React from "react";
import { create } from "zustand";
import { QueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
export type Row = Record<string, any>;
export const qc = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});
export async function api(path: string, body?: unknown) {
  const r = await fetch(
    "/api/" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const j = await r.json();
  if (!r.ok) throw Error(j.error || "服务请求失败");
  return j;
}
export const useUI = create<{
  page: string;
  go: (x: string) => void;
  detail: Row | null;
  show: (x: Row | null) => void;
  msg: string;
  tell: (x: string) => void;
  id: number | null;
  researchMarket: Row | null;
  chooseResearchMarket: (market: Row) => void;
  open: (x: number | null) => void;
}>((set) => ({
  page: "总览",
  go: (page) => set({ page }),
  detail: null,
  show: (detail) => set({ detail }),
  msg: "",
  tell: (msg) => set({ msg }),
  id: null,
  researchMarket: null,
  chooseResearchMarket: (researchMarket) => set({researchMarket}),
  open: (id) => set({ id }),
}));
export const f = (x: unknown, n = 2) =>
  typeof x === "number"
    ? x.toLocaleString("en-US", {
        maximumFractionDigits: n,
        minimumFractionDigits: n,
      })
    : "—";
export const time = (t: number) =>
  t ? new Date(t * 1000).toISOString().slice(11, 19) : "—";
export const tr: Record<string, string> = {
  CREATED: "等待启动",
  PAUSED: "已暂停",
  RUNNING: "运行中",
  ERROR: "异常",
  DATA_STALE: "行情中断",
  INITIALIZING: "初始化",
  COMPLETED: "已结算",
  STOPPED: "已停止",
  history: "历史归档",
  public: "实时行情",
  csv: "导入行情",
  paper: "本地模拟",
  demo: "交易所模拟",
  live: "真实账户",
  normal: "普通交易",
  challenge: "24H 翻倍挑战",
  ai: "AI 增强",
  rules: "规则引擎",
  spot: "现货",
  swap: "USDT 永续",
};
export const txt = (x: string) => tr[x] || x;
export function Panel({
  title,
  cap,
  children,
}: {
  title: string;
  cap?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <header>
        <h3>{title}</h3>
        <small>{cap}</small>
      </header>
      {children}
    </section>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Table({
  heads,
  rows,
  click,
}: {
  heads: string[];
  rows: React.ReactNode[][];
  click?: (i: number) => void;
}) {
  return rows.length ? (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            {heads.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              tabIndex={click ? 0 : undefined}
              onClick={() => click?.(i)}
              onKeyDown={(e) => e.key === "Enter" && click?.(i)}
            >
              {r.map((x, j) => (
                <td key={j}>{x}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <p className="empty">暂无符合条件的记录</p>
  );
}
function Sizing({ detail }: { detail: Row }) {
  const c = detail.data?.calculation;
  if (!c) return null;
  return <section className="sizing">
    <h3>仓位计算明细</h3>
    <p>净资产 {f(c.nav, 4)} USDT　目标 {f(c.target_pct)}%　单笔风险预算 {f(c.risk_per_trade_pct)}%
      {c.compatibility_default && "（旧配置兼容默认值）"}</p>
    <Table heads={["限制项", "成本预留前 USDT", "允许金额 USDT", "占净资产"]}
      rows={(c.limits || []).map((r: Row) => [r.name, f(r.raw_amount, 6), f(r.amount, 6), f(r.pct, 3) + "%"])} />
    <p><b>最终可执行 {f(c.final_amount, 6)} USDT　/　{f(c.final_pct, 3)}%</b></p>
    <p>{c.reason}</p>
    <p>单边手续费 {f(c.fee_pct, 3)}%　单边滑点预留 {f(c.slippage_pct, 3)}%　
      估算手续费 {f(c.estimated_fee, 6)} USDT　软件金额门槛 {f(c.software_min, 4)} USDT</p>
    <small>{c.formula}</small>
    <p>{c.precision_status}</p>
    {c.quantity != null && <p>取整数量 {f(c.quantity, 10)}　执行价格 {f(c.price, 8)}　
      数量步长 {f(c.rule_step, 10)}　最小数量 {f(c.rule_minimum, 10)}　规则最低金额 {f(c.rule_min_cost, 4)} USDT</p>}
  </section>;
}

export function Modal() {
  const { detail, show } = useUI();
  return (
    <Dialog.Root open={!!detail} onOpenChange={(v) => !v && show(null)}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="modal" aria-describedby={undefined}>
          <Dialog.Close className="close" aria-label="关闭">
            <X size={15} />
          </Dialog.Close>
          <small>RECORD INSPECTOR</small>
          <Dialog.Title>{detail?.title || "记录详情"}</Dialog.Title>
          <p>{detail?.summary}</p>
          {detail && <Sizing detail={detail} />}
          {detail?.id && (
            <p>
              市场时间 {time(detail.t)} UTC　 /　 记录 #{detail.id}{" "}
              <button
                onClick={() => navigator.clipboard.writeText(String(detail.id))}
              >
                复制编号
              </button>
            </p>
          )}
          {detail?.data?.metrics && (
            <div className="explanation">
              {[
                [
                  "01　候选机会",
                  detail.symbol + " · 机会评分 " + detail.data.metrics.score,
                ],
                [
                  "02　信号依据",
                  (detail.data.metrics.signals || []).join("、") ||
                    "未触发组合策略",
                ],
                [
                  "03　仓位与成本",
                  "建议名义金额 " +
                    f(detail.data.amount, 4) +
                    " USDT，预估滑点 " +
                    f(detail.data.metrics.slip * 100, 3) +
                    "%",
                ],
                [
                  "04　风险与退出",
                  detail.data.risks +
                    "；初始止损 " +
                    detail.data.exits?.stop +
                    "%，移动回撤 " +
                    detail.data.exits?.trail +
                    "%",
                ],
              ].map(([k, v]) => (
                <section key={k}>
                  <small>{k}</small>
                  <p>{v}</p>
                </section>
              ))}
            </div>
          )}
          <details open={!detail?.data?.metrics}>
            <summary>完整记录</summary>
            <pre>{JSON.stringify(detail?.data ?? detail, null, 2)}</pre>
          </details>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export async function run(task: () => Promise<unknown>, success = "已保存") {
  try {
    await task();
    await qc.invalidateQueries();
    useUI.getState().tell(success);
  } catch (e) {
    useUI.getState().tell(String(e instanceof Error ? e.message : e));
  }
}
