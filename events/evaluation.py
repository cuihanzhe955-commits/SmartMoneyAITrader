"""Time-forward paired scoring; no future settlement is spent at entry time."""
import math
from decimal import Decimal
from events.lab import D


def evaluate(lab, sid):
    reconciliation=lab.reconcile(sid)
    with lab.brain.db() as db:
        import json
        row=db.execute("SELECT * FROM event_lab_sessions WHERE id=?",(sid,)).fetchone()
        if not row:raise ValueError("研究会话不存在")
        cfg=json.loads(row["config"]);state=json.loads(row["state"])
        rounds=[dict(r,data=json.loads(r["data"])) for r in db.execute("SELECT * FROM event_lab_rounds WHERE session_id=? ORDER BY created_at,id",(sid,))]
    paired=[]
    for r in rounds:
        d=r["data"];f=d.get("forecasts",{})
        if r["status"]!="SETTLED" or not all(k in f and f[k].get("probability") is not None for k in ("with_memory","without_memory")):continue
        if d["decision_at"]>=d["expires_at"] or d["settlement"]["resolved_at"]<=d["decision_at"]:continue
        paired.append(r)
    result={}
    for variant in ("without_memory","with_memory"):
        scored=[];events=[]
        for r in paired:
            d=r["data"];f=d["forecasts"][variant];p=f["probability"];y=d["payout"]
            # Fractional/void outcomes are soft labels, not counted as a binary win.
            clamp=max(1e-12,min(1-1e-12,p))
            scored.append(((p-y)**2,-(y*math.log(clamp)+(1-y)*math.log(1-clamp))))
            events.extend([(d["decision_at"],1,r["id"],d),(d["settled_at"],0,r["id"],d)])
        cash=D(cfg["capital"]);open_positions={};realized=Decimal(0);peak=cash;dd=0.;participated=0;skipped=0;costs=Decimal(0)
        for when,kind,rid,d in sorted(events,key=lambda e:(e[0],e[1],e[2])):
            f=d["forecasts"][variant];snap=d["snapshot"]
            if kind==1:
                qty=D(snap["modeled_shares"]);cost=D(snap["modeled_total"]).quantize(Decimal('.000001'),rounding="ROUND_UP")
                condition=snap["condition_id"]
                allowed=(f["action"]=="BUY" and snap["research_feasible"] and qty>0 and
                    D(f["probability"])*qty-cost>qty*D(cfg["min_edge"]) and cost<=cash and cost<=D(cfg["per_trade"]) and
                    len(open_positions)<cfg["max_positions"] and not any(v[2]==condition for v in open_positions.values()) and
                    realized>-D(cfg["capital"])*D(cfg["max_loss_pct"])/100)
                if allowed:
                    cash-=cost;open_positions[rid]=(qty,cost,condition);participated+=1
                    costs+=D(snap["modeled_fee"])+D(snap["rounding_reserve"])
                else:skipped+=1
            elif rid in open_positions:
                qty,cost,_=open_positions.pop(rid);payout=qty*D(d["payout"])
                cash+=payout;realized+=payout-cost
            equity=cash+sum((v[1] for v in open_positions.values()),Decimal(0))
            peak=max(peak,equity);dd=max(dd,float((peak-equity)/peak*100))
        result[variant]=dict(samples=len(scored),brier=sum(x[0] for x in scored)/len(scored) if scored else None,
            log_loss=sum(x[1] for x in scored)/len(scored) if scored else None,reference_net=float(realized),
            max_cost_basis_drawdown_pct=dd,skip_ratio=skipped/len(scored) if scored else None,participated=participated,
            estimated_fee_and_reserve=float(costs),open_positions=len(open_positions))
    return dict(session_id=sid,paired_rounds=len(paired),variants=result,reconciliation=reconciliation,
        actual=dict(predicted=sum(bool(r["data"].get("forecasts")) for r in rounds),
            participated=sum(bool(r["data"].get("order")) for r in rounds),
            settled=sum(r["status"]=="SETTLED" for r in rounds),failed=sum(r["status"]=="FAILED" for r in rounds),
            skipped=sum(r["data"].get("action")=="SKIP" for r in rounds),
            reference_cash=float(state["cash"]),reference_realized=float(state["realized"])),
        method="Same captured snapshot, model and time-forward memory cutoff; only complete paired resolved rounds. Independent variant cash replay.",
        equity_basis="cash plus open positions at cost; NOT mark-to-market drawdown",calibration_verified=False,
        future_leakage_controls=True,execution_enabled=False)
