"""Browser/API acceptance with a fake exchange, temporary ledger and no external network."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve():
    import uvicorn
    from unittest.mock import Mock, patch
    from terminal.runtime import Runtime
    from terminal.api import create_app
    from test_acceptance import wire_venue
    v = wire_venue()
    v.env = "demo"; v.client.set_sandbox_mode(True)
    orders = {}
    v.permission_check = Mock(return_value={"venue_account_id": "fixture-uid"})
    v.preflight = Mock(side_effect=lambda state: dict(venue_account_id="fixture-uid", checked=int(time.time()), dedicated_balance_match=True))
    v.audit_spot = Mock(return_value={"dedicated_balance_match": True})
    v.algo_inventory = Mock(side_effect=lambda: [o for o in orders.values() if o["state"] == "live"])
    v.quote = Mock(side_effect=lambda symbol: (100, 101, time.time()))
    v.client.load_markets = Mock(return_value=v.client.markets)
    def create(p):
        cid = p["algoClOrdId"]
        assert cid not in orders
        orders[cid] = dict(p, algoId="fixture-"+str(len(orders)), instType="SPOT", state="live", uTime="1000", actualSz="0", ordIdList=[])
        return {"code":"0","data":[dict(sCode="0",algoId=orders[cid]["algoId"],algoClOrdId=cid)]}
    def cancel(params):
        o=next(o for o in orders.values() if o["algoId"]==params[0]["algoId"])
        o.update(state="canceled",uTime="1001")
        return {"code":"0","data":[dict(sCode="0",algoId=o["algoId"])]}
    v.client.privatePostTradeOrderAlgo=Mock(side_effect=create)
    v.client.privatePostTradeCancelAlgos=Mock(side_effect=cancel)
    def lookup(cid):
        order=orders[cid]
        if Path(os.environ["SMART_MONEY_RUNTIME"],"trigger-fixture").exists() and order["state"]=="live":
            order.update(state="effective",uTime="1002",ordIdList=["fixture-child"],actualSz=order["sz"])
        return order.copy()
    v.lookup_stop=Mock(side_effect=lookup)
    v.client.fetch_order=Mock(return_value=dict(id="fixture-child",symbol="BTC/USDT",side="sell",amount=.1,filled=.04,status="canceled"))
    v.executions=Mock(return_value=[dict(id="fixture-fill",order="fixture-child",symbol="BTC/USDT",side="sell",amount=.04,price=89,
                                        fee=dict(currency="USDT",cost=.00356))])
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):
                raise RuntimeError("browser test prohibits external network")
    sys.addaudithook(guard)
    with patch.object(Runtime,"venue",lambda self,c:v):
        uvicorn.run(create_app(),host="127.0.0.1",port=int(sys.argv[2]),log_level="error")


def run():
    from playwright.sync_api import sync_playwright
    from terminal.runtime import Runtime
    from terminal.config import Session
    out=Path(os.environ["SMART_MONEY_UI_OUTPUT"]);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        rt=Runtime(temp)
        rt.vault.update("okx/demo",{"key":"fixture","secret":"fixture","passphrase":"fixture"})
        with rt.db.db:
            s=rt.new(Session(consent=True))
            s["config"].update(exchange="okx",execution="demo",product="spot",source="public")
            s.update(account_ref=rt.account_ref(s["config"]),cash=90,venue_account_id="fixture-uid")
            s["positions"]["BTC"]=dict(qty=.1,cost=10,price=100,high=100,entry=100,opened=s["t"],opening_order="entry1")
            rt.db.save(s)
        rt.shutdown();rt.db.db.close()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        url="http://127.0.0.1:"+str(port)
        proc=subprocess.Popen([sys.executable,"-X","utf8","-B",__file__,"--serve",str(port)],cwd=ROOT,
            env={**os.environ,"SMART_MONEY_RUNTIME":temp})
        try:
            for _ in range(100):
                try:
                    with urlopen(url+"/api/health",timeout=1):break
                except OSError:time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel="chrome")
                page=browser.new_page(viewport={"width":1366,"height":768})
                errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
                page.goto(url)
                page.locator("aside").get_by_role("button",name="设置",exact=True).click()
                page.get_by_text("模拟平台联调准备 · 查看待办",exact=True).click()
                prep=page.get_by_label("模拟平台联调准备")
                prep.get_by_role("button",name="运行模拟只读预检",exact=True).click()
                prep.get_by_text("本机准备条件与只读预检已就绪；平台成交验收仍未完成。",exact=True).wait_for()
                assert not page.request.get(url+"/api/demo-readiness").json()["platform_integration_verified"]
                page.evaluate("""() => {
                    const tag=document.createElement('div');
                    tag.textContent='自动化测试 · 平台回报为 Mock · 未进行平台账户联调';
                    tag.style='position:fixed;bottom:0;right:0;z-index:1000;background:#1d3557;color:white;padding:4px';
                    document.body.append(tag);
                }""")
                page.get_by_label("模拟保护止损价").fill("90")
                page.get_by_role("button",name="创建模拟保护",exact=True).click()
                page.get_by_role("cell",name="待触发记录",exact=True).wait_for(timeout=15000)
                page.get_by_role("button",name="核对时间线",exact=True).click()
                timeline=page.get_by_label("保护单核对时间线")
                timeline.get_by_text("本机记录，不代替平台账户联调或实盘验收",exact=True).wait_for()
                assert timeline.get_by_text("发送前已持久化",exact=False).count()>0
                with page.expect_download() as download:
                    timeline.get_by_role("button",name="导出本页核对报告",exact=True).click()
                assert download.value.suggested_filename.startswith("protection-page-")
                for width,height in [(1366,768),(1920,1080)]:
                    page.set_viewport_size({"width":width,"height":height})
                    for theme in ("dark","light"):
                        if page.evaluate("document.body.classList.contains('light')") != (theme=="light"):
                            page.get_by_label("切换主题").click()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.screenshot(path=str(out/("hosted-"+str(width)+"-"+theme+".png")),full_page=True)
                page.get_by_role("button",name="核对时间线",exact=True).click()
                page.get_by_role("button",name="撤销模拟保护",exact=True).click()
                page.get_by_role("cell",name="已取消",exact=True).wait_for(timeout=15000)
                page.get_by_role("button",name="核对账户并释放",exact=True).click()
                page.get_by_role("cell",name="核对完成 · 已释放",exact=True).wait_for(timeout=15000)
                assert not page.request.get(url+"/api/protection-status").json()["blocks_orders"]
                actual=page.request.get(url+"/api/state").json()["state"]
                assert actual["lifecycle_status"]=="PAUSED" and not actual["admitted"]
                page.get_by_label("模拟保护止损价").fill("89")
                page.get_by_role("button",name="创建模拟保护",exact=True).click()
                page.get_by_role("cell",name="待触发记录",exact=True).wait_for(timeout=15000)
                status=page.request.get(url+"/api/protection-status").json()
                assert len(status["orders"])==2 and status["blocks_orders"]
                page.screenshot(path=str(out/"replacement.png"),full_page=True)
                Path(temp,"trigger-fixture").touch()
                # Wait for the actual background task to settle the fixture child.
                page.wait_for_function("""async () => {
                    const s=await (await fetch('/api/protection-status')).json();
                    return s.orders.length===2 && s.orders.every(o=>o.released);
                }""",timeout=15000)
                page.get_by_role("cell",name="核对完成 · 已释放",exact=True).nth(1).wait_for(timeout=10000)
                latest=page.request.get(url+"/api/protection-status").json()["orders"][0]
                proof=page.request.get(url+"/api/protection-report?id="+str(latest["session_id"])+"&client_id="+latest["client_id"]).json()
                assert proof["children"][0]["receipt"]["qty"]==.04
                page.get_by_role("button",name="核对时间线",exact=True).first.click()
                timeline=page.get_by_label("保护单核对时间线").first
                try:
                    timeline.get_by_text("已核对成交量 0.04",exact=False).wait_for(timeout=12000)
                except Exception:
                    page.screenshot(path=str(out/"timeline-failure.png"),full_page=True)
                    (out/"timeline-failure.html").write_text(page.content(),encoding="utf8")
                    raise
                final=page.request.get(url+"/api/state").json()["state"]
                assert abs(final["positions"]["BTC"]["qty"]-.06)<1e-12
                assert abs(final["cash"]-(90+3.56-.00356))<1e-10
                assert final["hosted_review_required"] and final["lifecycle_status"]=="PAUSED"
                page.screenshot(path=str(out/"partial-fill-handover.png"),full_page=True)
                assert not errors,errors
                browser.close()
            print("PASS browser create/query/cancel/release/replacement; 2 sizes x 2 themes; fixture exchange only")
        finally:
            proc.terminate();proc.wait(15)


if __name__=="__main__":
    serve() if "--serve" in sys.argv else run()
