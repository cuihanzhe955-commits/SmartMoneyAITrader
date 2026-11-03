"""Stable IDs for one session, account, product and observed market signal."""
import hashlib
import json


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(",", ":")).encode("utf8")
    return hashlib.sha256(raw).hexdigest()


def scope(state):
    c = state["config"]
    return [state["id"], c.get("exchange", "archive"), c.get("execution", "paper"),
            c.get("product", "spot"), state.get("account_ref", "paper")]


def signal_key(state, symbol, side, bar):
    # A retry, a model change or a different reason cannot mint a second order.
    return digest([scope(state), symbol, side, bar])


def position_version(state):
    return digest([state["cash"], {k: [p["qty"], p["cost"], p["opened"]]
                                   for k, p in state["positions"].items()}])


def decision_tag(state, symbol, side, metrics):
    signal = signal_key(state, symbol, side, metrics["time"])
    ai = metrics.get("proposal")
    source = "local_stop" if metrics.get("protective") else "ai" if ai else "rules"
    quote_id = digest([scope(state), symbol, metrics["time"], metrics["price"]])
    snapshot = quote_id if metrics.get("protective") else (ai or {}).get("snapshot_id") or state.get("market_version") or quote_id
    return {"signal_id": signal, "decision_id": digest([signal, source, snapshot]),
            "source": source, "snapshot_id": snapshot, "proposal": ai,
            "config_version": digest(state["config"]), "protective": bool(metrics.get("protective"))}

