"use strict";
const $ = (s) => document.querySelector(s),
  app = $("#app"),
  dlg = $("#modal");
const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (x, d = 2) =>
  Number(x).toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
const clock = (t) => (t ? new Date(t * 1000).toISOString().slice(11, 19) : "—");
const states = {
  CREATED: "等待开始",
  INITIALIZING: "初始化中",
  RUNNING: "运行中",
  SCANNING: "扫描市场",
  ANALYZING: "分析机会",
  RISK_CHECK: "风控审核",
  EXECUTING: "模拟执行",
  MONITORING: "管理持仓",
  WAITING: "等待下一轮",
  PAUSED: "已暂停",
  DATA_STALE: "行情已过期",
  ERROR: "运行异常",
  STOPPED: "已停止",
  COMPLETED: "挑战结束",
};
let zoom = false;
let data = {},
  view = "challenge",
  id = "",
  feed = [],
  ledger = [],
  page = 0,
  frozen = false,
  sym = "",
  kind = "",
  range = 24,
  table = "orders",
  busy = false,
  gen = 0,
  lastForm = false;
const btn = (a, t, cl = "") =>
  `<button type="button" class="${cl}" data-act="${a}">${t}</button>`;
const options = (list, val) =>
  list
    .map((x) => `<option ${x === val ? "selected" : ""}>${esc(x)}</option>`)
    .join("");
const end = (s) => ["STOPPED", "COMPLETED"].includes(s.lifecycle_status);
const get = async (url, body) => {
  const r = await fetch(
    url,
    body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {},
  );
  const j = await r.json();
  if (!r.ok) throw Error(j.error);
  return j;
};
const toast = (t) => {
  $("#toast").textContent = t;
  setTimeout(() => {
    $("#toast").textContent = "";
  }, 3500);
};
function modal(title, body) {
  $("#detail").innerHTML =
    `<div class="eyebrow">TERMINAL INSPECTOR</div><h2>${esc(title)}</h2>${body}`;
  if (!dlg.open) dlg.showModal();
}
$("#close").onclick = () => dlg.close();
const graphic = `<svg viewBox="0 0 480 230" role="img" aria-label="轨道速度仪图形"><defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#293347" stroke-width=".7"/></pattern></defs><rect width="480" height="230" fill="url(#grid)"/><g fill="none" transform="translate(260 116) rotate(-23)"><ellipse rx="146" ry="66" stroke="#39445e"/><ellipse rx="122" ry="52" stroke="#776bb9"/><ellipse rx="96" ry="41" stroke="#46455e" stroke-dasharray="3 6"/><ellipse rx="160" ry="58" transform="rotate(-23)" stroke="#615540"/><path d="M-125 35Q-24 100 109 -23" stroke="#ff9b42" stroke-width="3"/><circle cx="109" cy="-23" r="5" fill="#ff9b42"/></g><path d="M200 90h27l17 36 34-65h28l-57 103h-13z" fill="#ad9bff"/><g fill="#91a0b5" font-family="Consolas" font-size="10"><text x="16" y="22">FIG. 01 / VELOCITY</text><text x="16" y="213">VIRTUAL CAPITAL LAB</text><text x="400" y="213">SYS. 024</text></g></svg>`;
const labels = {
  interval: "扫描间隔（秒）",
  frame: "决策周期（分钟）",
  trend: "趋势确认（分钟）",
  candidates: "候选币数上限",
  slots: "同时持仓数",
  target: "目标仓位 / 净资产 %",
  utilization: "总持仓 / 净资产上限 %",
  concentration: "单币 / 净资产上限 %",
  stop: "初始止损 / 入场价 %",
  profit: "止盈 / 入场价 %",
  trail: "移动回撤 / 最高价 %",
  cooldown: "开仓冷却（秒）",
  breaker: "熔断回撤 / 峰值净资产 %",
  fee: "单边手续费 / 成交额 %",
};
function wizard() {
  lastForm = true;
  const c = data.defaults;
  app.innerHTML = `<div class="head"><div><div class="eyebrow">EXPERIMENT LAB　/　CHALLENGE 24</div><h1>24小时翻倍挑战</h1><p class="sub">为本次实验分配虚拟资金，配置规则后手动启动。</p></div><b class="pill orange">●　待配置</b></div><div class="setup"><section class="card poster">${graphic}<div class="inside"><div class="eyebrow">VELOCITY TERMINAL　//　01</div><h2>DOUBLE CHALLENGE</h2><p class="sub">在一个完整的市场日里，观察纯规则引擎如何捕捉动量、分配仓位与控制回撤。</p><br><div class="spec"><span>实验目标</span><b class="orange mono">+100%</b></div><div class="spec"><span>市场时间窗口</span><b class="mono">24:00:00</b></div><div class="spec"><span>执行环境</span><b>无杠杆 · 独立模拟账户</b></div></div></section>
<form id="setup" class="card"><div class="panelhead"><h2>创建挑战</h2><span class="tag">SESSION SETUP</span></div>
<div class="step"><h3><span class="num">01</span>分配模拟本金</h3><div class="choices"><input aria-label="模拟本金" name="capital" required type="number" min=".01" max="1000000000" step="any" value="10"><span class="unit">USDT</span>　${[10, 20, 50, 100].map((n) => btn("amount" + n, n, n === 10 ? "sel" : "")).join("")}</div></div>
<div class="step"><h3><span class="num">02</span>实验期限与结算</h3><div class="choices"><span class="tag">固定 24 小时</span><select name="settlement" aria-label="结算政策"><option value="mark">按最终有效行情估值</option><option value="close">尝试模拟平仓</option></select></div></div>
<div class="step"><h3><span class="num">03</span>交易风格 <small>　狂飙进攻型</small></h3><div class="choices">${["综合狂飙", "快速动量", "突破追踪"].map((s, i) => btn("preset" + s, s, i ? "" : "sel")).join("")}</div><input type="hidden" name="preset" value="综合狂飙"></div>
<div class="step"><h3><span class="num">04</span>市场数据</h3><div class="choices"><select name="source" aria-label="行情来源"><option value="history">本地历史行情回放</option><option value="public">实时公共行情 · Binance</option></select><select name="speed" aria-label="回放倍率">${[1, 60, 120, 600, 3600].map((x) => `<option value="${x}" ${x === 120 ? "selected" : ""}>${x}× 回放</option>`).join("")}</select></div><small id="sourcehint">Binance 现货归档 · 2024-08-05 UTC · 8 个交易对 · 1 分钟收盘数据</small></div>
<div class="step"><details><summary>高级策略参数</summary><div class="params">${Object.entries(
    labels,
  )
    .map(
      ([k, v]) =>
        `<label>${v}${["frame", "trend"].includes(k) ? `<select name="${k}">${options(k === "frame" ? [1, 5, 15] : [5, 15], c[k])}</select>` : `<input name="${k}" type="number" required step="any" value="${c[k]}">`}</label>`,
    )
    .join(
      "",
    )}<label>动量 / 量能 / 趋势 / 波动 / 突破权重<input name="weights" value="25,25,20,15,15"></label></div><small>单笔风险预算为净资产的 1%。参数为实验初始值。</small></details></div>
<div class="step"><h3><span class="num">05</span>风险确认</h3><label><input name="consent" type="checkbox" required> 本实验仅使用虚拟资金，可能损失全部模拟本金。24小时翻倍不是收益保证。</label></div><div class="inside row"><small>无需钱包或 API 密钥</small><button class="primary" type="submit">创建独立挑战　→</button></div></form></div>`;
}
function chart(s) {
  const c = s.config,
    values = data.curve.filter((r) => r[0] >= s.t - range * 3600),
    series = values.length ? values : [[s.start, c.capital]];
  const lo =
      Math.min(...series.map((r) => r[1]), c.capital) * (zoom ? 0.998 : 0.97),
    hi =
      Math.max(...series.map((r) => r[1]), (zoom ? 1 : 2) * c.capital) *
      (zoom ? 1.002 : 1.03);
  const first = series[0][0],
    last = Math.max(first + 60, series.at(-1)[0]),
    x = (t) => 45 + (595 * (t - first)) / (last - first),
    y = (n) => 164 - (141 * (n - lo)) / (hi - lo);
  let line = series
    .map(([t, n], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(n).toFixed(1)}`)
    .join(" ");
  return `<svg class="chart" viewBox="0 0 660 190" role="img" aria-label="实验净资产曲线">${[0, 1, 2, 3, 4].map((i) => `<path d="M45 ${23 + 35 * i}H640" stroke="#263248" stroke-dasharray="2 5"/>`).join("")}${[
    [2 * c.capital, "#ff9b42"],
    [c.capital, "#91a0b5"],
  ]
    .filter(([v]) => v <= hi && v >= lo)
    .map(
      ([v, col]) =>
        `<path d="M45 ${y(v)}H640" stroke="${col}" stroke-dasharray="5 5"/><text x="3" y="${y(v) + 3}" fill="${col}" font-size="11">${num(v, 1)}</text>`,
    )
    .join(
      "",
    )}<path d="${line}" fill="none" stroke="#a998ff" stroke-width="2.5"/>${data.marks
    .filter((r) => r[0] >= first && r[0] <= last)
    .map(
      ([t, k]) =>
        `<circle cx="${x(t)}" cy="${y(series.find((r) => r[0] >= t)?.[1] ?? c.capital)}" r="2.3" fill="${k === "BUY" ? "#24c78e" : "#f26372"}"><title>${clock(t)} ${k}</title></circle>`,
    )
    .join(
      "",
    )}<text x="45" y="185" fill="#91a0b5" font-size="10">${clock(first)} UTC</text><text x="640" y="185" text-anchor="end" fill="#91a0b5" font-size="10">${clock(last)}</text></svg>`;
}
const panel = (title, aside, body) =>
  `<section class="card"><div class="panelhead"><h2>${title}</h2>${aside}</div>${body}</section>`;
const gridtable = (heads, rows) =>
  rows.length
    ? `<div class="scroll"><table><thead><tr>${heads.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    : '<div class="empty">暂无记录</div>';
const tr = (cells, attrs = "") =>
  `<tr ${attrs}>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
function dashboard() {
  const s = data.state,
    c = s.config,
    nav = data.nav,
    ret = (nav / c.capital - 1) * 100,
    remain = Math.max(0, s.deadline - data.now),
    tm = [
      Math.floor(remain / 3600),
      Math.floor((remain % 3600) / 60),
      remain % 60,
    ]
      .map((v) => String(v).padStart(2, "0"))
      .join(":");
  const mt = (k, v, unit, sub, cl = "") =>
    `<div class="metric"><span class="sub">${k}</span><div class="big ${cl}">${v} <span class="unit">${unit}</span></div><small>${sub}</small></div>`;
  const buttons = end(s)
    ? btn("new", "创建新挑战　＋", "primary")
    : s.lifecycle_status === "CREATED"
      ? btn("start", "开始挑战　▶", "primary") + btn("end", "结束")
      : (s.lifecycle_status === "PAUSED" ||
        s.lifecycle_status === "ERROR" ||
        s.lifecycle_status === "DATA_STALE"
          ? s.breaker
            ? ""
            : btn("resume", "恢复扫描", "primary")
          : btn("pause", "Ⅱ　暂停")) +
        btn("end", "结束") +
        btn("stop", "紧急停止", "danger");
  app.innerHTML = `<div class="head"><div><div class="eyebrow">VELOCITY TERMINAL　/　SESSION ${String(s.id).padStart(3, "0")}</div><h1>24小时翻倍挑战</h1><span class="tag">纯规则</span> <span class="tag purple">模拟交易</span> <span class="tag orange">极高风险</span></div><div class="actions">${buttons}</div></div><div class="metrics card">${mt("当前净资产", num(nav, 3), "USDT", "初始本金　" + num(c.capital))}${mt("挑战收益率", (ret >= 0 ? "+" : "") + num(ret), "%", "实验目标　+100%", ret >= 0 ? "green" : "red")}${mt("距离目标", num(Math.max(0, 2 * c.capital - nav), 3), "USDT", "目标净资产　" + num(2 * c.capital))}${mt("剩余市场时间", tm, "", c.source === "history" ? `历史回放　${c.speed}×` : "实时公共行情", "orange")}</div>
<div class="status"><b class="${s.lifecycle_status === "RUNNING" ? "green" : "orange"}">● ${states[s.lifecycle_status]}${s.lifecycle_status === "RUNNING" ? " · " + states[s.current_activity] : ""}</b><span>${c.source === "history" ? "Binance 历史归档" : "Binance 公共现货"} · UTC</span><span>最近扫描 ${clock(s.last_scan)}</span><span>下轮 ${clock(end(s) || s.lifecycle_status === "PAUSED" ? 0 : s.next_scan)}</span><span>行情更新 ${clock(s.radar[0]?.time)}</span><span>采样延迟 ${s.delay ?? "—"} 秒</span><span>心跳 ${clock(s.heartbeat)}</span><span>最近决策 ${esc(s.latest)}</span>${["PAUSED", "DATA_STALE", "ERROR"].includes(s.lifecycle_status) || s.pending ? '<b class="orange">估值暂停 · 显示最后有效价格</b>' : ""}</div>
<div class="grid">${panel("实验净资产曲线", `<span>${btn("zoom", zoom ? "完整目标" : "放大波动", "mini")} <select class="mini" aria-label="曲线时间范围" id="range">${[1, 6, 24].map((n) => `<option value="${n}" ${range === n ? "selected" : ""}>${n} 小时</option>`).join("")}</select></span>`, chart(s) + '<div class="key"><span class="purple">━ 净资产</span>　┄ 初始资金　<span class="orange">┄ 翻倍目标</span>　<span class="green">● 买</span> / <span class="red">卖 · 熔断</span></div>')}${panel(
    "机器决策直播",
    btn("freeze", frozen ? "继续滚动" : "暂停滚动", "mini"),
    `<div class="choices" style="padding:8px 14px"><select id="sym" class="mini" aria-label="筛选币种"><option value="">全部币种</option>${options(["BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "ADA"], sym)}</select><select class="mini" id="kind" aria-label="筛选事件"><option value="">全部事件</option>${options(["SCAN", "ANALYZING", "BUY", "SELL", "HOLD", "EXIT", "REJECT", "RISK_CHECK", "FILLED", "ERROR", "BREAKER"], kind)}</select></div><div class="feed">${
      feed
        .slice(0, 20)
        .map(
          (r, i) =>
            `<div class="event" role="button" tabindex="0" data-event="${i}"><time class="muted">${clock(r.t)}</time><div><b class="${r.kind === "FILLED" ? "green" : "purple"}">${r.symbol || "SYS"}　${r.kind}</b><br>${esc(r.summary)}</div></div>`,
        )
        .join("") || '<div class="empty">等待匹配事件</div>'
    }</div><div class="row" style="padding:6px 14px">${btn("prev", "‹ 上页", "mini")}<small>${page + 1}</small>${btn("next", "下页 ›", "mini")}</div>`,
  )}</div>
<div class="lower">${panel(
    "高波动市场雷达",
    '<span class="tag">RADAR / ' + s.radar.length + "</span>",
    gridtable(
      ["标的", "机会评分", "相对量能"],
      s.radar.map((m) =>
        tr([
          `<b>${m.symbol}</b> <small>/ USDT</small>`,
          `${m.score}<span class="bar"><span style="width:${Math.max(0, m.score)}%"></span></span>`,
          num(m.relative) + "×",
        ]),
      ),
    ),
  )}${panel(
    "当前持仓与仓位管理",
    btn("assets", "资产明细", "mini"),
    gridtable(
      ["标的", "入场价", "估值价", "市值 USDT", "浮动盈亏"],
      Object.entries(s.positions).map(([k, p]) =>
        tr([
          k,
          num(p.entry, 5),
          num(p.price, 5),
          num(p.qty * p.price, 3),
          num(p.qty * p.price - p.cost, 4),
        ]),
      ),
    ) +
      `<div class="inside sub">可用现金　${num(s.cash, 4)} USDT　 ·　 已用仓位　${Object.keys(s.positions).length} / ${c.slots}</div>`,
  )}</div>
${panel(
  "最近交易与决策流水",
  `<div>${btn("orders", "订单", "mini " + (table === "orders" ? "sel" : ""))} ${btn("decisions", "决策", "mini " + (table === "decisions" ? "sel" : ""))}</div>`,
  gridtable(
    ["时间 UTC", "币种", "动作 / 状态", "名义金额 USDT", "原因", "详情"],
    ledger
      .slice(0, 10)
      .map((r, i) =>
        tr([
          clock(r.t),
          r.symbol,
          (r.data.side ? r.data.side + " · " : "") + r.kind,
          r.data.nominal !== undefined ? num(r.data.nominal, 4) : "—",
          esc(r.summary),
          btn("record" + i, "查看", "mini"),
        ]),
      ),
  ),
)}
<div class="inside row"><span class="sub">策略 ${s.version} · ${c.preset}</span>${btn("config", "参数快照", "mini")}</div>${data.report ? panel("挑战结算报告", '<span class="tag orange">SETTLEMENT</span>', `<div class="inside"><p>${data.report.pending ? "结算待确认 · 最后有效估值" : "最终净资产"}　<b>${num(data.report.nav, 4)} USDT</b>　 成交 ${data.report.fills} 次　 最大回撤 ${num(data.report.max_drawdown)}%</p><p class="sub">${data.report.notice}</p><br>${btn("report", "完整报告", "mini")}　${["html", "csv", "json"].map((x) => `<a href="/export/${x}?id=${s.id}" download>导出 ${x.toUpperCase()}</a>`).join("　")}</div>`) : ""}`;
}
async function refresh(force = false) {
  const n = ++gen,
    route = view;
  const d = await get("/api/state" + (id ? "?id=" + id : ""));
  if (n !== gen || route !== view) return;
  data = d;
  document
    .querySelectorAll("[data-nav]")
    .forEach((b) => b.classList.toggle("active", b.dataset.nav === view));
  if (view === "overview" || view === "history") {
    const list = await get("/api/history");
    if (n !== gen) return;
    app.innerHTML = `<div class="head"><div><div class="eyebrow">SMART MONEY　/　WORKSPACE</div><h1>${view === "history" ? "挑战档案" : "工作台总览"}</h1></div>${btn("challenge", "进入挑战　→", "primary")}</div>${panel(
      "独立模拟实验",
      '<span class="tag">SESSION ARCHIVE</span>',
      gridtable(
        ["挑战编号", "状态", "净资产 USDT", "数据源", "实验记录"],
        list.map((v) =>
          tr([
            String(v.id).padStart(3, "0"),
            states[v.status],
            num(v.nav, 4),
            v.source === "history" ? "历史回放" : "公共行情",
            btn("open" + v.id, "进入", "mini"),
          ]),
        ),
      ),
    )}`;
    return;
  }
  if (!d.state || view === "new") {
    if (!lastForm || force) wizard();
    return;
  }
  lastForm = false;
  const query = `&id=${d.state.id}`,
    [events, records] = await Promise.all([
      frozen && !force
        ? Promise.resolve(feed)
        : get(
            `/api/events?table=events&page=${page}&symbol=${sym}&kind=${kind}${query}`,
          ),
      get("/api/events?table=" + table + query),
    ]);
  if (n !== gen) return;
  feed = events;
  ledger = records;
  const scroll = $(".feed")?.scrollTop || 0;
  dashboard();
  if ($(".feed")) $(".feed").scrollTop = scroll;
}
function inspect(r) {
  modal(
    `${r.symbol || "SYS"} · ${r.kind}`,
    `<p>${esc(r.summary)}　<small>${clock(r.t)} UTC</small></p><pre>${esc(JSON.stringify(r.data, null, 2))}</pre>${btn("copy" + r.id, "复制记录编号", "mini")} ${r.data.order_id ? btn("orderid" + r.data.order_id, "打开对应订单", "mini") : ""}`,
  );
}
document.addEventListener("click", async (e) => {
  const el = e.target.closest("button,[data-event]");
  if (!el) return;
  try {
    if (el.dataset.nav) {
      id = "";
      view = el.dataset.nav;
      lastForm = false;
      await refresh(true);
      return;
    }
    if (el.dataset.event !== undefined) {
      inspect(feed[+el.dataset.event]);
      return;
    }
    const a = el.dataset.act;
    if (!a) return;
    if (a.startsWith("amount") || a.startsWith("preset")) {
      const f = $("#setup"),
        is = a.startsWith("amount");
      f.elements[is ? "capital" : "preset"].value = a.slice(6);
      el.parentElement
        .querySelectorAll("button")
        .forEach((b) => b.classList.toggle("sel", b === el));
      return;
    }
    if (a.startsWith("copy")) {
      await navigator.clipboard.writeText(a.slice(4));
      toast("已复制编号");
      return;
    }
    if (a.startsWith("orderid")) {
      inspect(await get(`/api/order?id=${data.state.id}&order=${a.slice(7)}`));
      return;
    }
    if (a.startsWith("record")) {
      inspect(ledger[+a.slice(6)]);
      return;
    }
    if (a === "zoom") {
      zoom = !zoom;
      dashboard();
      return;
    }
    if (a === "report") {
      const r = data.report;
      const titles = {
        challenge_id: "实验编号",
        start: "开始时间 UTC",
        end: "结束时间 UTC",
        source: "行情来源",
        version: "策略版本",
        capital: "初始本金 USDT",
        nav: "最终估值 USDT",
        return_pct: "净收益率 %",
        max_drawdown: "最大回撤 %",
        fills: "模拟成交次数",
        win_rate: "已平仓胜率",
        payoff: "平均盈利 / 平均亏损",
        fees: "累计手续费 USDT",
        slippage: "累计滑点成本 USDT",
        rejections: "风控拒单次数",
        loss_streak: "最大连续亏损次数",
      };
      modal(
        "完整结算报告",
        Object.entries(titles)
          .map(([k, v]) => {
            let x = r[k];
            if (k === "start" || k === "end")
              x = new Date(x * 1000)
                .toISOString()
                .replace("T", " ")
                .slice(0, 19);
            else if (k === "win_rate" && x !== null) x = num(x * 100) + "%";
            else if (typeof x === "number" && !Number.isInteger(x))
              x = num(x, 5);
            return `<div class="spec"><span>${v}</span><b>${esc(x ?? "无可用样本")}</b></div>`;
          })
          .join("") +
          Object.entries({
            best: "最佳交易",
            worst: "最差交易",
            contributions: "各币种盈亏贡献",
            holding_times: "持仓时间分布",
            config: "参数快照",
          })
            .map(
              ([k, v]) =>
                `<details><summary>${v}</summary><pre>${esc(JSON.stringify(r[k], null, 2))}</pre></details>`,
            )
            .join("") +
          '<p class="sub">' +
          r.notice +
          "</p>",
      );
      return;
    }
    if (a === "config") {
      modal(
        a === "report" ? "完整结算报告" : "独立参数快照",
        `<pre>${esc(JSON.stringify(a === "report" ? data.report : data.state.config, null, 2))}</pre>`,
      );
      return;
    }
    if (a === "assets") {
      const s = data.state;
      modal(
        "资产明细",
        Object.entries({
          可用现金: s.cash,
          持仓市值: data.nav - s.cash,
          已实现盈亏: s.realized,
          未实现盈亏: data.nav - s.config.capital - s.realized,
          累计手续费: s.fees,
          累计滑点成本: s.slippage,
          "当前回撤 %": s.dd,
          "最大回撤 %": s.max_dd,
        })
          .map(([k, v]) => `<div class="spec">${k}<b>${num(v, 5)}</b></div>`)
          .join(""),
      );
      return;
    }
    if (["end", "stop"].includes(a)) {
      modal(
        a === "end" ? "结束本次挑战？" : "紧急停止挑战？",
        `<p class="inside">${a === "end" ? "将按创建时的结算政策处理持仓并生成报告。" : "立即停止扫描与下单，保留全部仓位和流水。"}</p>${btn("confirm" + a, "确认" + (a === "end" ? "结束" : "停止"), "danger")}`,
      );
      return;
    }
    if (["start", "pause", "resume", "confirmend", "confirmstop"].includes(a)) {
      await get("/api/action/" + a.replace("confirm", ""), {
        id: data.state.id,
      });
      dlg.close();
    } else if (a === "challenge" || a === "new" || a.startsWith("open")) {
      view = a === "new" ? "new" : "challenge";
      id = a.startsWith("open") ? a.slice(4) : "";
      page = 0;
      frozen = false;
      sym = "";
      kind = "";
    } else if (a === "freeze") {
      frozen = !frozen;
      dashboard();
      return;
    } else if (a === "prev" || a === "next") {
      if (a === "next" && feed.length < 21) return;
      page = Math.max(0, page + (a === "next" ? 1 : -1));
      frozen = page > 0;
    } else if (a === "orders" || a === "decisions") table = a;
    await refresh(true);
  } catch (err) {
    toast(err.message);
  }
});
document.onkeydown = (e) => {
  if (e.key === "Enter" && e.target.dataset.event !== undefined)
    e.target.click();
};
document.onchange = async (e) => {
  const t = e.target;
  if (t.name === "source") {
    const live = t.value === "public";
    $("#setup").elements.speed.disabled = live;
    $("#sourcehint").textContent = live
      ? "Binance 只读公共行情 · 启动时检查可达性和延迟"
      : "Binance 现货归档 · 2024-08-05 UTC · 8 个交易对 · 1 分钟收盘数据";
    return;
  }
  if (t.id === "range") range = +t.value;
  else if (t.id === "sym") sym = t.value;
  else if (t.id === "kind") kind = t.value;
  else return;
  page = 0;
  await refresh(true);
};
document.onsubmit = async (e) => {
  if (e.target.id !== "setup") return;
  e.preventDefault();
  const f = e.target,
    b = Object.fromEntries(new FormData(f));
  Object.keys(b).forEach((k) => {
    if (typeof data.defaults[k] === "number") b[k] = +b[k];
  });
  b.weights = b.weights.split(",").map(Number);
  b.consent = f.elements.consent.checked;
  try {
    await get("/api/create", b);
    view = "challenge";
    id = "";
    await refresh(true);
  } catch (err) {
    toast(err.message);
  }
};
async function poll() {
  try {
    if (!dlg.open && (!lastForm || !data.defaults) && view === "challenge")
      await refresh();
  } catch (e) {
    toast("无法读取本地服务 · " + e.message);
  } finally {
    setTimeout(poll, 1100);
  }
}
poll();
