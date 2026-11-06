"""The scheduler alone consumes proposals. Workers never place or mutate orders."""
import time
from uuid import uuid4

from ai.provider import Provider
from ai.worker import Inference
from execution.identity import digest, position_version, scope
from strategy.ensemble import enrich
from strategy.rules import analyze
from terminal.settings import AIConfig
from challenge.clock import market_time


def expired(stamp, s, market_time, *, same_snapshot):
    if time.time() >= stamp["expires_at"] or market_time >= stamp["market_deadline"]:
        return "提案有效期已过"
    if stamp["scope"] != scope(s) or stamp["revision"] != s.get("revision", 0):
        return "会话、平台、账户、产品或会话版本已变更"
    if stamp["config"] != digest(s["config"]) or stamp["provider"] != s.get("ai_signature"):
        return "策略或模型配置版本已变更"
    if stamp["portfolio"] != position_version(s):
        return "余额或持仓已变化"
    if same_snapshot and stamp["snapshot_id"] != s.get("market_version"):
        return "行情快照已更新"
    return ""


class Coordinator:
    def __init__(self):
        self.worker = Inference()
        self.brain = None

    def decide(self, db, s, bars, t, vault):
        cfg = AIConfig(**vault.values.get("ai_config", {}))
        key = vault.values.get("ai_key", "")
        signature = digest([cfg.model_dump(), key])
        s["ai_signature"] = signature
        ready = self.worker.poll()
        advice = None
        if ready:
            status, stamp, value = ready
            reason = expired(stamp, s, max(t, market_time(s)), same_snapshot=True)
            if reason or status != "READY":
                self.failure(db, s, cfg, reason or value, stamp,
                             "AI_SKIP" if reason or status == "TIMEOUT" else "AI_ERROR")
            elif not s.get("ai_manual"):
                brief, response = value
                s.update(ai_failed=False, ai_status="模型提案已核验", ai_request=stamp["request_id"])
                advice = {**response.model_dump(), "_stamp": stamp}
                db.record("system_events", s, "AI", brief[:1000], data=advice)
                if advice["action"] == "SKIP":
                    db.record("decisions", s, "SKIP", advice["reason"], data=advice)
                # A completed decision is consumed once. SKIP/HOLD stay in effect
                # for this snapshot until expiry instead of reverting mid-bar.
                s["ai_last_advice"] = advice
        cached = s.get("ai_last_advice")
        if cached and expired(cached["_stamp"], s, t, same_snapshot=True):
            s.pop("ai_last_advice", None)
            cached = None
        interval_due = (time.time() >= s.get("ai_next_wall", 0)
                        and t - s.get("ai_last", 0) >= cfg.interval)
        if (not s.get("ai_manual") and interval_due and self.worker.flight is None
                and s.get("ai_requested_snapshot") != s["market_version"]):
            if s.get("ai_calls", 0) + 2 > cfg.calls or not key:
                msg = "AI 会话调用预算已用完" if key else "缺少 AI 密钥"
                if s.get("ai_status") != msg:
                    self.failure(db, s, cfg, msg, {}, "AI_ERROR")
            else:
                metrics = []
                for symbol, rows in sorted(bars.items()):
                    try:
                        metrics.append(dict(symbol=symbol, **enrich(rows, analyze(rows, t, s["config"]), s["config"])))
                    except ValueError:
                        continue
                if metrics and not (set(s["positions"]) - {m["symbol"] for m in metrics}):
                    received = time.time()
                    bar = min(m["time"] for m in metrics)
                    stamp = dict(request_id=uuid4().hex, session_id=s["id"], scope=scope(s),
                                 revision=s.get("revision", 0), config=digest(s["config"]),
                                 portfolio=position_version(s), provider=signature, model=cfg.model,
                                 snapshot_id=s["market_version"], market_time=bar,
                                 issued_at=received, expires_at=received + cfg.ttl,
                                 market_deadline=min(t + cfg.ttl, bar + 120))
                    try:
                        provider = Provider(cfg.model_dump(), key)
                        if self.brain is not None and s["config"].get("execution","paper")=="paper":
                            memory_scope=f"spot:{s['config'].get('exchange','okx')}:{s['id']}"
                            provider.memory_context=lambda: self.brain.retrieve(memory_scope,received,bar)
                    except ValueError as err:
                        self.failure(db, s, cfg, str(err), stamp, "AI_ERROR")
                    else:
                        s.update(ai_requested_snapshot=s["market_version"], ai_last=t,
                                 ai_calls=s.get("ai_calls", 0) + 2, ai_next_wall=received + cfg.interval)
                        if not s.get("ai_failed"):
                            s["ai_status"] = "等待模型，规则扫描与保护继续"
                        db.record("system_events", s, "AI_REQUEST", "已预留本轮两次模型调用", data=stamp)
                        db.save(s)
                        db.db.commit()  # reserve the budget before contacting the provider
                        self.worker.start(stamp, provider, metrics, tuple(s["positions"]), cfg.timeout)
        failure_blocks = bool(s.get("ai_manual") or (s.get("ai_failed") and cfg.fallback == "hold"))
        if failure_blocks:
            return None, True
        # A cached BUY/SELL is never executed again. Rule scanning between model
        # calls continues; persistent signal keys also guard retries at execution.
        if cached and cached["action"] in ("SKIP", "HOLD"):
            return cached, True
        return advice, False

    @staticmethod
    def failure(db, s, cfg, reason, stamp, event):
        s.pop("ai_last_advice", None)
        s.update(ai_failed=True, ai_status=reason)
        if cfg.fallback == "manual":
            s["ai_manual"] = True
        db.record("system_events", s, event, reason,
                  data={"request": stamp, "fallback": cfg.fallback})
        db.record("decisions", s, "SKIP", reason,
                  data={"request": stamp, "source": "ai", "fallback": cfg.fallback})

