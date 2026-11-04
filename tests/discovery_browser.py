"""Discovery UX verification with labelled fixtures and no external connections."""
import os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def serve():
    import uvicorn
    from market.discovery import Discovery
    from test_discovery import fixture,NOW
    from terminal.api import create_app
    from unittest.mock import patch
    original=Discovery.run
    def run(self,q):
        if q.search=="ERROR":raise ValueError("浏览器验收：公开接口限频，未重试")
        if q.search=="SLOW":time.sleep(1)
        result=original(self,q)
        result["source"]="浏览器测试替身 / 合成协议数据，非真实行情"
        return result
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):raise RuntimeError("discovery browser prohibits external network")
    sys.addaudithook(guard)
    with patch("market.discovery.public_client",side_effect=lambda name:fixture(name)[0]),patch.object(Discovery,"run",run):
        # Use a fixed research clock; Runtime keeps the real system clock.
        app=create_app()
        original_lifespan=app.router.lifespan_context
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def life(a):
            async with original_lifespan(a):
                a.state.discovery.clock=lambda:NOW
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
                page.goto(url);page.locator("aside").get_by_role("button",name="策略实验室",exact=True).click()
                page.get_by_role("heading",name="动态市场发现与预算预检",exact=True).wait_for()
                page.get_by_text("尚未查询。",exact=False).wait_for()
                button=page.get_by_role("button",name="发现并预检交易对",exact=True)
                button.click();page.locator("[data-discovery-result=okx]").wait_for()
                page.get_by_text("通过研究筛选 3 对",exact=False).wait_for()
                page.get_by_role("button",name="研究筛选通过 · 查看计算",exact=True).first.click()
                page.get_by_role("dialog").get_by_text("研究预算",exact=False).wait_for()
                page.screenshot(path=str(out/"discovery-budget-detail.png"),full_page=True)
                page.keyboard.press("Escape")
                for width,height in [(1366,768),(1920,1080)]:
                    page.set_viewport_size({"width":width,"height":height})
                    for theme in ("dark","light"):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=="light"):page.get_by_label("切换主题").click()
                        page.evaluate("window.scrollTo(0,0)")
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.screenshot(path=str(out/("discovery-"+str(width)+"-"+theme+".png")),full_page=True)
                page.get_by_label("研究白名单").fill("BTC,ETH");page.get_by_label("研究黑名单").fill("ETH")
                button.click();page.get_by_text("通过研究筛选 1 对",exact=False).wait_for()
                page.get_by_label("单笔研究预算 USDT").fill("1");button.click()
                page.get_by_text("不满足交易所金额限额",exact=False).first.wait_for()
                page.get_by_label("研究搜索币种").fill("SLOW");button.click()
                page.get_by_role("button",name="正在读取公开行情…",exact=True).wait_for()
                assert page.request.get(url+"/api/health").status==200
                page.get_by_text("显示 0 对",exact=False).wait_for()
                page.get_by_label("研究搜索币种").fill("ERROR");button.click();page.get_by_role("alert").get_by_text("限频",exact=False).wait_for()
                page.screenshot(path=str(out/"discovery-network-error.png"),full_page=True)
                assert page.request.get(url+"/api/state").json()["state"] is None
                assert not errors,errors
                for context in browser.contexts:
                    for tab in context.pages:tab.goto("about:blank")
                browser.close()
            print("PASS discovery UI: filters, budget details, no-session mutation, loading, empty, error, 2 sizes x 2 themes")
        finally:proc.terminate();proc.wait(15)


if __name__=="__main__":serve() if "--serve" in sys.argv else run()
