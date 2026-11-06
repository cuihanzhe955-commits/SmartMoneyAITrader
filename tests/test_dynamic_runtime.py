import copy,threading,time
from unittest.mock import Mock,patch
import pytest
from terminal.runtime import Runtime
from terminal.config import Session
from market.discovery import evaluate
from execution.venue import MarketBatch
from market.feeds import START,historical
from test_discovery import fixture


def setup(tmp_path):
    rt=Runtime(tmp_path);rt.background=True
    with rt.db.db:
        s=rt.new(Session(consent=True,source="public",market_mode="dynamic",capital=1000,
            target=50,concentration=100,risk_per_trade_pct=20,cooldown=0,candidates=2,slots=1,
            interval=1,scanner=dict(whitelist=["NEW"])))
        rt.command(s["id"],"start")
    return rt


def install(rt,clock):
    c,ticks=fixture(symbols=("NEW",))
    def discover(q):
        for tick in ticks.values():tick["timestamp"]=clock[0]*1000
        return evaluate(c,c.markets,ticks,q,clock[0])
    rt.discovery_service.run=Mock(side_effect=discover)
    v=Mock()
    def bars(*args,**kwargs):
        raw=historical(START+(clock[0]-int(time.time()))//60*60)["BTC"]
        ratio=100/raw[-1][4];batch=MarketBatch()
        batch["NEW"]=[(r[0]+clock[0]-raw[-1][0],*(x*ratio for x in r[1:5]),r[5]) for r in raw]
        return batch
    v.bars.side_effect=bars
    def rules(symbols):
        from execution.market_rules import spot_rules
        return {k:dict(rule=dict(spot_rules(c.markets[k+"/USDT"],c.precisionMode,k+"/USDT"),limits=c.markets[k+"/USDT"]["limits"]),checked_at=clock[0],exchange="okx",product="spot") for k in symbols if k+"/USDT" in c.markets}
    v.public_rules.side_effect=rules
    return v


def cycle(rt):
    rt.tick()
    task=rt.discovery_worker.flight
    if task:assert task.done.wait(2)
    rt.tick()
    task=rt.market_worker.flight
    if task:assert task.done.wait(2)
    rt.tick()


def positive(rows,m,c):m.update(score=100,buy=True,signals=["合成验收信号"],trend=0,momentum=0)


def test_dynamic_candidate_outside_original_eight_enters_and_fills_through_risk(tmp_path):
    rt=setup(tmp_path);clock=[int(time.time())];v=install(rt,clock)
    try:
        with patch("terminal.runtime.Venue",return_value=v),patch("terminal.runtime.market_time",side_effect=lambda _:clock[0]),patch("strategy.ensemble.enrich",side_effect=positive):
            cycle(rt);s=rt.db.load()
            assert s["scan_pool"]["entries"]==["NEW"] and "NEW" in s["paper_pending"]
            assert not s["positions"]
            assert s["scan_pool"]["requested_candidates"]==2 and s["scan_pool"]["discovery_execution_enabled"]
            rt.tick();assert rt.db.load()["scan_pool"]["fetched_count"]==1
            clock[0]+=60;cycle(rt);s=rt.db.load()
            assert "NEW" in s["positions"] and s["cash"]>=0
            fill=rt.db.entries("fills",s["id"])[0]
            assert fill["data"]["calculation"]["precision_status"].startswith("公开规则校验通过")
            assert fill["data"]["nominal"]+fill["data"]["fee"]<=1000
            from execution import live
            assert not live.unresolved(rt.db)
    finally:rt.shutdown();rt.db.db.close()


def test_slow_discovery_does_not_block_held_symbol_market_monitoring(tmp_path):
    rt=setup(tmp_path);clock=[int(time.time())];v=install(rt,clock);entered,release=threading.Event(),threading.Event()
    original=rt.discovery_service.run.side_effect
    def slow(q):entered.set();assert release.wait(3);return original(q)
    rt.discovery_service.run.side_effect=slow
    try:
        with rt.db.db:
            s=rt.db.load();s["positions"]["NEW"]=dict(qty=.1,price=100,cost=10,entry=110,high=110,opened=clock[0]);s["cash"]-=10;rt.db.save(s)
        # Full slots would skip discovery; allow another slot for this scenario.
        with rt.db.db:
            s=rt.db.load();s["config"]["slots"]=2;rt.db.save(s)
        with patch("terminal.runtime.Venue",return_value=v),patch("terminal.runtime.market_time",side_effect=lambda _:clock[0]),patch("strategy.ensemble.enrich",side_effect=positive):
            start=time.monotonic();rt.tick();assert time.monotonic()-start<.3
            assert entered.wait(1);assert rt.market_worker.flight.done.wait(2);rt.tick()
            s=rt.db.load();assert s["feed_valid"] and s["scan_pool"]["required"]==["NEW"]
            assert not s["scan_pool"]["entries"]
            assert s["paper_pending"]["NEW"]["side"]=="SELL"
            assert not rt.discovery_worker.flight.done.is_set()
    finally:release.set();rt.shutdown();rt.db.db.close()


def test_pause_and_restart_cannot_apply_late_discovery_to_another_platform(tmp_path):
    rt=setup(tmp_path);clock=[int(time.time())];v=install(rt,clock);entered,release=threading.Event(),threading.Event()
    original=rt.discovery_service.run.side_effect
    def slow(q):entered.set();assert release.wait(3);return original(q)
    rt.discovery_service.run.side_effect=slow
    try:
        rt.tick();assert entered.wait(1);old=rt.discovery_worker.flight
        with rt.db.db:
            rt.command(rt.db.load()["id"],"stop")
            new=rt.new(Session(consent=True,source="public",exchange="binance",market_mode="dynamic"));rt.command(new["id"],"start")
        release.set();assert old.done.wait(2)
        rt.tick();assert rt.db.load()["config"]["exchange"]=="binance"
        assert not rt.db.load().get("discovery_report") and not rt.db.load()["positions"]
    finally:release.set();rt.shutdown();rt.db.db.close()


def test_optional_scan_hang_does_not_block_independent_paper_stop_and_fill(tmp_path):
    rt=setup(tmp_path);clock=[int(time.time())];v=install(rt,clock)
    entered,release=threading.Event(),threading.Event();slow=Mock()
    def stuck(*a,**k):entered.set();assert release.wait(4);return MarketBatch()
    slow.bars.side_effect=stuck
    try:
        with rt.db.db:
            s=rt.db.load();s["positions"]["NEW"]=dict(qty=.1,price=100,cost=11,entry=110,high=110,opened=clock[0]);s["cash"]-=11;rt.db.save(s)
        def factory(*a):return v if threading.current_thread().name=="smart-money-market-fetch" and rt.paper_protection_client.active else slow
        # Candidate lane is deliberately blocked; held-only lane has a separate transport.
        with patch("terminal.runtime.Venue",side_effect=factory),patch("terminal.runtime.market_time",side_effect=lambda _:clock[0]):
            rt.tick();assert entered.wait(1)
            start=time.monotonic();rt.protection_tick();assert time.monotonic()-start<.3
            assert rt.paper_protection_worker.flight.done.wait(2);rt.protection_tick()
            s=rt.db.load();assert s["paper_pending"]["NEW"]["side"]=="SELL"
            assert not rt.market_worker.flight.done.is_set()
            clock[0]+=60;rt.paper_protection_next=0
            with patch("terminal.runtime.time.time",return_value=clock[0]):
                rt.protection_tick();assert rt.paper_protection_worker.flight.done.wait(2);rt.protection_tick()
            s=rt.db.load();assert not s["positions"] and len(rt.db.entries("fills",s["id"]))==1, (s.get("paper_watch"),s.get("paper_pending"),rt.db.entries("system_events",s["id"],5))
            assert s["paper_watch"]["status"]=="READY"
            assert not rt.market_worker.flight.done.is_set()
    finally:release.set();rt.shutdown();rt.db.db.close()


def test_discovery_region_error_pauses_without_retry(tmp_path):
    rt=setup(tmp_path);rt.discovery_service.run=Mock(side_effect=ValueError("HTTP 451 · 地区限制"))
    try:
        rt.tick();assert rt.discovery_worker.flight.done.wait(2);rt.tick()
        assert rt.db.load()["lifecycle_status"]=="PAUSED"
        for _ in range(3):rt.tick()
        assert rt.discovery_service.run.call_count==1
    finally:rt.shutdown();rt.db.db.close()


def test_ai_dynamic_proposal_uses_same_risk_and_paper_executor(tmp_path):
    from ai.provider import Advice
    rt=setup(tmp_path);clock=[int(time.time())];v=install(rt,clock)
    try:
        with rt.db.db:
            s=rt.db.load();s["config"]["engine"]="ai";rt.db.save(s)
            rt.vault.update_many({"ai_key":"fixture-key","ai_config":dict(model="mock",base="https://fixture.invalid/v1",fallback="hold")})
        proposal=Advice(symbol="NEW",action="BUY",fraction=.1,reason="合成模型提案",risk="合成测试",exit_plan="独立风控")
        with patch("terminal.runtime.Venue",return_value=v),patch("terminal.runtime.market_time",side_effect=lambda _:clock[0]),patch("terminal.runtime.Provider.propose",return_value=("合成研究",proposal)),patch("strategy.ensemble.enrich",side_effect=lambda rows,m,c:m.update(buy=False,trend=0,momentum=0)):
            cycle(rt)
            task=rt.ai.worker.flight
            if task:assert task.done.wait(2)
            cycle(rt)
            s=rt.db.load();assert s["paper_pending"]["NEW"]["source"]=="ai"
            assert s["paper_pending"]["NEW"]["amount"]<=100
            clock[0]+=60;cycle(rt);s=rt.db.load()
            assert "NEW" in s["positions"]
            fills=rt.db.entries("fills",s["id"])
            assert fills[0]["data"]["source"]=="ai" and fills[0]["data"]["nominal"]<=100
    finally:rt.shutdown();rt.db.db.close()
