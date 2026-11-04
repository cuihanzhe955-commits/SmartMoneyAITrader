import React, {useEffect, useRef, useState} from "react";
import {createChart, AreaSeries, ColorType, createSeriesMarkers, type UTCTimestamp} from "lightweight-charts";
import {Panel, type Row} from "./shared";
import {prepareCurve} from "./chart-data";

export function Curve({d}: {d: Row}) {
  const ref = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState(24);
  const [light, setLight] = useState(document.body.classList.contains("light"));
  const [error, setError] = useState("");
  const data = prepareCurve(d, range);
  const capital = d.state?.config?.capital;
  const target = d.state?.config?.profile === "challenge" ? capital*2 : null;
  const version = JSON.stringify([data.points, data.markers, capital, target]);
  useEffect(() => {
    const observer = new MutationObserver(() => setLight(document.body.classList.contains("light")));
    observer.observe(document.body, {attributes: true, attributeFilter: ["class"]});
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!ref.current || !data.points.length) return;
    let chart: ReturnType<typeof createChart> | undefined;
    try {
      chart = createChart(ref.current, {autoSize: true,
        layout: {background: {type: ColorType.Solid, color: "transparent"}, textColor: light ? "#56657b" : "#99a8bf", attributionLogo: true},
        grid: {vertLines: {color: "#7888a51a"}, horzLines: {color: "#7888a525"}},
        timeScale: {timeVisible: true, secondsVisible: false}, handleScroll: false, handleScale: false});
      const series = chart.addSeries(AreaSeries, {lineColor: "#9885ff", topColor: "#9581ff44", bottomColor: "#9581ff02", lineWidth: 2});
      series.setData(data.points.map(p => ({...p, time: p.time as UTCTimestamp})));
      if (typeof capital === "number" && Number.isFinite(capital)) series.createPriceLine({price: capital, color: "#8391aa", lineWidth: 1, lineStyle: 2, title: "初始"});
      if (typeof target === "number" && Number.isFinite(target)) series.createPriceLine({price: target, color: "#edaa60", lineWidth: 1, lineStyle: 2, title: "目标"});
      createSeriesMarkers(series, data.markers.map(m => ({...m, time: m.time as UTCTimestamp})));
      chart.timeScale().fitContent();
      setError("");
    } catch {
      setError("图表暂时无法渲染，请刷新页面；账本数据不会因此改变。");
    }
    return () => chart?.remove();
  }, [version, light]);
  return <Panel title="账户净值" cap="EQUITY / USDT">
    <div className="plotbar"><span>●　策略净值</span><select aria-label="净值显示范围" value={range} onChange={e => setRange(+e.target.value)}>{[1,6,24].map(n => <option key={n} value={n}>{n} 小时</option>)}</select></div>
    <div className="chart" ref={ref} data-chart-theme={light ? "light" : "dark"} data-chart-points={data.points.length} data-chart-markers={data.markers.length} data-chart-last={data.points.at(-1)?.value} />
    {!data.points.length && <p className="pad">暂无有效净值数据</p>}
    {!!data.rejected && <p className="pad">已排除 {data.rejected} 条无效或未来时点记录，请核对数据源。</p>}
    {error && <p role="alert" className="pad">{error}</p>}
    <small className="pad"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></small>
  </Panel>;
}
