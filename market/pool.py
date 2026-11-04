"""Separate entry eligibility from mandatory position/order monitoring."""
import re


def names(values):
    result=[]
    for value in values:
        if not isinstance(value,str) or not re.fullmatch(r"[A-Z0-9]{1,30}",value):
            raise ValueError("监控币种标识无效，禁止静默丢弃持仓")
        if value not in result:result.append(value)
    return result


def plan(candidates,positions=(),pending=(),blacklist=()):
    held,orders,deny=names(positions),names(pending),set(names(blacklist))
    entries=[k for k in names(candidates) if k not in deny]
    required=names([*held,*orders])
    monitored=names([*required,*entries])
    return dict(entries=entries,required=required,monitor=monitored,
        entry_count=len(entries),required_count=len(required),monitor_count=len(monitored),
        retained={k:[reason for reason,group in (("持仓",held),("在途委托",orders)) if k in group] for k in required})


def from_discovery(report,exchange,now,positions=(),pending=(),blacklist=()):
    # This adapter deliberately does not grant execution permission. Runtime
    # activation is separate; stale/wrong-venue reports cannot admit new entries.
    entries=[];rejected=0;status="ready"
    if (not isinstance(report,dict) or report.get("exchange")!=exchange or
        report.get("read_only") is not True or report.get("changes_sessions") is not False or
        not isinstance(report.get("rows"),list)):
        status="invalid_report"
    else:
        for row in report["rows"]:
            if not isinstance(row,dict) or row.get("eligible") is not True:continue
            stamp=row.get("source_timestamp");symbol=row.get("symbol")
            if (type(stamp) not in (int,float) or not 0<=now-stamp<=120 or
                not isinstance(symbol,str) or not re.fullmatch(r"[A-Z0-9]{1,30}/USDT",symbol)):
                rejected+=1;continue
            entries.append(symbol[:-5])
        if rejected:status="partially_stale"
    return dict(plan(entries,positions,pending,blacklist),source="discovery_preview",
                admission=status,rejected_rows=rejected,execution_enabled=False)
