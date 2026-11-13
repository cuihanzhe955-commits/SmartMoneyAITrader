"""E-stage UI acceptance against explicit fixtures in an isolated temporary ledger."""
import os,socket,subprocess,sys,tempfile,time,json
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def serve():
    import uvicorn
    from unittest.mock import patch,Mock
    from test_discovery import fixture
    from market.discovery import Discovery,evaluate
    from execution.venue import Venue
    from market.feeds import historical,START
    from terminal.api import create_app
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):
                raise RuntimeError("E browser prohibits external network")
    sys.addaudithook(guard)
    def discover(self,q):
        c,t=fixture(q.exchange,symbols=("NEW",))
        now=time.time()
        for tick in t.values():tick["timestamp"]=now*1000
        if q.exchange=="gate":
            c.markets["NEW/USDT"]["info"]={"trade_status":"tradable","min_base_amount":".001"}
            for tick in t.values():tick["timestamp"]=None
        result=evaluate(c,c.markets,t,q,now)
        result["source"]="浏览器测试替身 / 合成数据，非平台联调"
        c.close();return result
    def venue(name,product,env):
        assert env=="public" and product=="spot"
        c,_=fixture(name,symbols=("NEW",));c.markets["NEW/USDT"]["info"]={"trade_status":"tradable","min_base_amount":".001"}
        def candles(*a,**k):
            now=int(time.time());raw=historical(START)["BTC"];ratio=100/raw[-1][4]
            return [[(r[0]+now-START-60)*1000,*(x*ratio for x in r[1:5]),r[5]/(r[4]*ratio)] for r in raw]
        c.fetch_ohlcv=Mock(side_effect=candles)
        v=Venue.__new__(Venue);v.name=name;v.swap=False;v.env=env;v.client=c
        return v
    with patch.object(Discovery,"run",discover),patch("terminal.runtime.Venue",side_effect=venue),patch("strategy.ensemble.enrich",side_effect=lambda rows,m,c:m.update(buy=False,trend=0,momentum=0)):
        uvicorn.run(create_app(),host="127.0.0.1",port=int(sys.argv[2]),log_level="error")


def run():
    from playwright.sync_api import sync_playwright
    out=Path(os.environ["SMART_MONEY_UI_OUTPUT"]);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        url=f"http://127.0.0.1:{port}"
        proc=subprocess.Popen([sys.executable,"-X","utf8","-B",__file__,"--serve",str(port)],cwd=ROOT,env={**os.environ,"SMART_MONEY_RUNTIME":temp})
        try:
            for _ in range(100):
                try:
                    with urlopen(url+"/api/health",timeout=1):break
                except OSError:time.sleep(.1)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel="chrome");page=browser.new_page(viewport={"width":1366,"height":768})
                errors=[];page.on("pageerror",lambda e:errors.append(str(e)));page.on("dialog",lambda d:d.accept())
                page.goto(url);page.locator("aside").get_by_role("button",name="实验功能",exact=True).click();page.get_by_role("button",name="配置普通交易",exact=False).click()
                page.get_by_label("行情来源",exact=False).select_option("public")
                page.get_by_label("入场候选来源",exact=True).select_option("dynamic")
                page.get_by_label("动态白名单",exact=True).press_sequentially("NEW,BTC")
                assert page.get_by_label("动态白名单",exact=True).input_value()=="NEW,BTC"
                page.get_by_label("动态白名单",exact=True).fill("NEW")
                assert page.get_by_label("模拟成交规则",exact=False).count()==0
                for width,height in ((1366,768),(1920,1080)):
                    page.set_viewport_size({"width":width,"height":height})
                    for theme in ("dark","light"):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=="light"):page.get_by_label("切换主题").click()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.screenshot(path=str(out/f"E-builder-{width}-{theme}.png"),full_page=True)
                page.get_by_label("01 · 执行环境",exact=False).select_option("live")
                assert page.get_by_label("入场候选来源",exact=True).count()==0
                assert "gate" not in page.get_by_label("主交易所",exact=True).locator("option").evaluate_all("xs=>xs.map(x=>x.value)")
                page.get_by_label("01 · 执行环境",exact=False).select_option("paper")
                page.get_by_label("入场候选来源",exact=True).select_option("dynamic")
                page.get_by_label("已确认账户",exact=False).check()
                page.get_by_role("button",name="创建会话",exact=False).click()
                page.get_by_role("button",name="开始运行",exact=True).wait_for()
                page.get_by_role("button",name="开始运行",exact=True).click()
                # Poll actual backend, not a front-end fixture response.
                for _ in range(100):
                    state=page.request.get(url+"/api/state").json()["state"]
                    if state.get("scan_pool",{}).get("entry_count")==1 and state.get("feed_valid"):break
                    page.wait_for_timeout(100)
                else:raise AssertionError(json.dumps(state,ensure_ascii=False))
                page.locator("aside").get_by_role("button",name="市场雷达",exact=True).click()
                page.locator("[data-monitor-pool]").get_by_text("动态模拟入场池",exact=False).wait_for()
                page.get_by_text("NEW / USDT",exact=True).wait_for()
                page.screenshot(path=str(out/"E-dynamic-radar.png"),full_page=True)
                page.locator("aside").get_by_role("button",name="设置",exact=True).click()
                page.locator("[data-platform-status]").get_by_text("结束当前会话",exact=False).first.wait_for()
                page.screenshot(path=str(out/"E-platform-active.png"),full_page=True)
                page.locator("aside").get_by_role("button",name="总览",exact=True).click()
                page.get_by_role("button",name="结束",exact=True).click()
                page.get_by_role("button",name="新建会话",exact=True).wait_for();page.get_by_role("button",name="新建会话",exact=True).click()
                page.get_by_label("行情来源",exact=False).select_option("public")
                page.get_by_label("主交易所",exact=True).select_option("gate")
                page.get_by_label("入场候选来源",exact=True).select_option("dynamic")
                page.get_by_label("已确认账户",exact=False).check();page.get_by_role("button",name="创建会话",exact=False).click()
                page.get_by_role("button",name="开始运行",exact=True).wait_for();page.get_by_role("button",name="开始运行",exact=True).click()
                for _ in range(100):
                    state=page.request.get(url+"/api/state").json()["state"]
                    if state.get("scan_pool",{}).get("rejections"):break
                    page.wait_for_timeout(100)
                else:raise AssertionError("Gate missing timestamp rejection absent")
                assert state["config"]["exchange"]=="gate" and not state["positions"] and not state.get("paper_pending")
                page.locator("aside").get_by_role("button",name="市场雷达",exact=True).click()
                page.locator("[data-monitor-pool]").get_by_text("时间缺失",exact=False).wait_for()
                page.screenshot(path=str(out/"E-gate-rejection.png"),full_page=True)
                assert not errors,errors
                page.goto("about:blank");browser.close()
                (out/"browser_result.json").write_text(json.dumps(dict(passed=True,external_network=False,real_accounts=False,fixtures=True,viewports=["1366x768","1920x1080"],themes=["dark","light"],screenshots=7),indent=2),encoding="utf-8")
                print("PASS E UI: dynamic settings, live-boundary, actual paper runtime, switch, Gate rejection, 2 sizes x 2 themes")
        finally:proc.terminate();proc.wait(15)


if __name__=="__main__":serve() if "--serve" in sys.argv else run()
