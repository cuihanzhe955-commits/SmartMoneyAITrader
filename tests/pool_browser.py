"""Monitor-pool UI regression with an explicitly labelled fixture and isolated DB."""
import os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def serve():
    import uvicorn
    from contextlib import asynccontextmanager
    from unittest.mock import Mock,patch
    from terminal.api import create_app
    from terminal.runtime import Runtime
    from terminal.config import Session
    from market.feeds import START,historical
    from test_monitor_pool import wire
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):raise RuntimeError("pool browser prohibits external network")
    sys.addaudithook(guard)
    with patch.object(Runtime,"start_worker",lambda self:None):
        app=create_app();original=app.router.lifespan_context
        @asynccontextmanager
        async def life(a):
            async with original(a):
                rt=a.state.rt;now=int(time.time());rows=historical(START)["BTC"];price=rows[-1][4]
                v=wire(("BTC","NEW"));v.client.fetch_ohlcv.return_value=[[(r[0]+now-START-60)*1000,r[1],r[2],r[3],r[4],r[5]/r[4]] for r in rows]
                rt.venue=Mock(return_value=v)
                with rt.lock,rt.db.db:
                    s=rt.new(Session(consent=True,source="public",strict_min=999999))
                    s["positions"]["NEW"]=dict(qty=.001,price=price,entry=price,high=price,cost=price*.001,opened=now)
                    s["cash"]-=price*.001;rt.db.save(s);rt.command(s["id"],"start")
                with patch("strategy.ensemble.enrich",side_effect=lambda rows,m,c:m.update(buy=False,trend=0,momentum=0)):rt.tick()
                with rt.lock,rt.db.db:
                    s=rt.db.load();s["scan_pool"]["source"]="浏览器验收测试替身";rt.db.save(s);rt.command(s["id"],"pause")
                yield
        app.router.lifespan_context=life
        uvicorn.run(app,host="127.0.0.1",port=int(sys.argv[2]),log_level="error")


def run():
    from playwright.sync_api import sync_playwright
    out=Path(os.environ["SMART_MONEY_UI_OUTPUT"]);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        url="http://127.0.0.1:"+str(port)
        proc=subprocess.Popen([sys.executable,"-X","utf8","-B",__file__,"--serve",str(port)],cwd=ROOT,env={**os.environ,"SMART_MONEY_RUNTIME":temp})
        try:
            for _ in range(100):
                try:
                    with urlopen(url+"/api/health",timeout=1):break
                except OSError:time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel="chrome");page=browser.new_page(viewport={"width":1366,"height":768})
                errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
                page.goto(url);page.locator("aside").get_by_role("button",name="市场雷达",exact=True).click()
                page.locator("[data-monitor-pool]").wait_for()
                page.get_by_text("本轮取得行情 2 币",exact=False).wait_for()
                page.get_by_text("NEW · 因持仓保留监控",exact=False).wait_for()
                page.get_by_text("ETH · 交易对不可用",exact=True).wait_for()
                for width,height in [(1366,768),(1920,1080)]:
                    page.set_viewport_size({"width":width,"height":height})
                    for theme in ("dark","light"):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=="light"):page.get_by_label("切换主题").click()
                        page.evaluate("window.scrollTo(0,0)")
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.screenshot(path=str(out/("pool-"+str(width)+"-"+theme+".png")),full_page=True)
                state=page.request.get(url+"/api/state").json()["state"]
                assert "NEW" in state["positions"] and not state["scan_pool"]["discovery_execution_enabled"]
                assert state["lifecycle_status"]=="PAUSED" and not errors,errors
                browser.close()
            print("PASS monitor pool UI: retained holdings, candidate errors, counts, paused simulation; 2 sizes x 2 themes")
        finally:proc.terminate();proc.wait(15)


if __name__=="__main__":serve() if "--serve" in sys.argv else run()
