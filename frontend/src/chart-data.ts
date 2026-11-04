export type Point = {time: number; value: number};
export type TradeMark = {time: number; position: "belowBar" | "aboveBar"; color: string; shape: "circle"; size: number};

export function prepareCurve(d: any, hours: number): {points: Point[]; markers: TradeMark[]; rejected: number} {
  const finite = (v: any) => typeof v === "number" && Number.isFinite(v);
  const timestamp = (v: any) => finite(v) && Number.isInteger(v) && v > 0;
  if (!d?.state || !timestamp(d.state.t) || !finite(hours) || hours <= 0) return {points: [], markers: [], rejected: 0};
  const values = new Map<number, number>();
  let rejected = 0;
  const source = Array.isArray(d.curve) ? d.curve : [];
  for (const row of source) {
    if (!Array.isArray(row) || !timestamp(row[0]) || !finite(row[1]) || row[0] > d.state.t) {rejected++; continue;}
    values.set(row[0], row[1]);
  }
  if (!source.length && timestamp(d.state.start) && d.state.start <= d.state.t && finite(d.state.config?.capital)) values.set(d.state.start, d.state.config.capital);
  const points = [...values].filter(([t]) => t >= d.state.t - hours * 3600).sort((a,b) => a[0]-b[0]).map(([time,value]) => ({time,value}));
  const times = new Set(points.map(p => p.time));
  const markers: TradeMark[] = (Array.isArray(d.fills) ? d.fills : [])
    .filter((f: any) => f && typeof f === "object" && timestamp(f.t) && times.has(f.t) && ["BUY","SELL"].includes(f.kind))
    .sort((a: any,b: any) => a.t-b.t)
    .map((f: any) => ({time: f.t, position: f.kind === "BUY" ? "belowBar" : "aboveBar", color: f.kind === "BUY" ? "#39cb9b" : "#f0798c", shape: "circle", size: .5}));
  return {points, markers, rejected};
}

export function replayCurve(data: ReturnType<typeof prepareCurve>, cutoff: number|null) {
  if (cutoff === null) return data;
  return {...data, points:data.points.filter(p=>p.time<=cutoff), markers:data.markers.filter(m=>m.time<=cutoff)};
}
