"""Full archive-ledger replay and labelled synthetic chart pressure test."""
import copy,json,os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def serve():
    import uvicorn
    from terminal.api import create_app
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):raise RuntimeError("replay acceptance prohibits external connections")
    sys.addaudithook(guard)
    uvicorn.run(create_app(),host="127.0.0.1",port=int(sys.argv[2]),log_level="error")


def run():
    from playwright.sync_api import sync_playwright
    from terminal.runtime import Runtime
    from terminal.config import Session
    from market.feeds import START,historical
    from challenge.manager import scan,finish
    out=Path(os.environ["SMART_MONEY_UI_OUTPUT"]);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        rt=Runtime(temp)
        with rt.db.db:
            s=rt.new(Session(consent=True))
            for minute in range(1441):scan(rt.db,s,START+minute*60,historical(START+minute*60),manage=minute<1440)
            finish(rt.db,s)
            count=len(rt.db.entries("fills",s["id"]));assert count>0
        rt.shutdown();rt.db.db.close()
        with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        url="http://127.0.0.1:"+str(port)
        proc=subprocess.Popen([sys.executable,"-X","utf8","-B",__file__,"--serve",str(port)],cwd=ROOT,env={**os.environ,"SMART_MONEY_RUNTIME":temp})
        try:
            for _ in range(100):
                try:
                    with urlopen(url+"/api/health",timeout=1):break
                except OSError:time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel="chrome");page=browser.new_page(viewport={"width":1366,"height":768});errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.goto(url);page.locator("[data-chart-points]").wait_for()
                before=page.request.get(url+"/api/state").json()
                page.evaluate("window.originalCanvas=document.querySelector('[data-chart-points] canvas')")
                page.get_by_label("切换主题").click();page.locator('[data-chart-theme="light"]').wait_for()
                assert page.evaluate("window.originalCanvas===document.querySelector('[data-chart-points] canvas')")
                page.get_by_role("button",name="开启图表回放",exact=True).click()
                slider=page.get_by_label("图表回放位置");slider.focus();slider.press("Home")
                page.locator('[data-chart-points="1"]').wait_for()
                page.locator('[data-replay-candles="240"]').wait_for()
                slider.press("ArrowRight");page.locator('[data-chart-points="2"]').wait_for()
                page.get_by_role("button",name="播放回放",exact=True).click()
                page.wait_for_function("Number(document.querySelector('[data-chart-points]').dataset.chartPoints)>2")
                page.get_by_role("button",name="暂停回放",exact=True).click()
                slider.focus();slider.press("End")
                symbol=before["fills"][0]["symbol"];page.get_by_label("K线回放币种").select_option(symbol)
                section=page.locator('section[aria-label="历史K线与成交回放"]')
                page.wait_for_function("Number(document.querySelector('[data-replay-fills]').dataset.replayFills)>0")
                section.get_by_role("table").filter(has=page.get_by_role("columnheader",name="已记录成交",exact=True)).get_by_role("row").nth(1).click()
                page.get_by_role("dialog").get_by_text("回放成交明细",exact=True).wait_for(timeout=5000);page.keyboard.press("Escape")
                for width,height in [(1366,768),(1920,1080)]:
                    page.set_viewport_size({"width":width,"height":height})
                    for theme in ("dark","light"):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=="light"):page.get_by_label("切换主题").click()
                        page.evaluate("window.scrollTo(0,0)")
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.screenshot(path=str(out/("replay-"+str(width)+"-"+theme+".png")),full_page=True)
                after=page.request.get(url+"/api/state").json()
                assert after["state"]==before["state"] and after["fills"]==before["fills"]
                page.get_by_role("button",name="返回最新图表",exact=True).click()
                page.get_by_role("button",name="开启图表回放",exact=True).wait_for()
                fallback=browser.new_page()
                fallback.add_init_script("HTMLCanvasElement.prototype.getContext=function(){return null;}")
                fallback.on("pageerror",lambda e:errors.append(str(e)))
                fallback.goto(url)
                fallback.get_by_role("alert").get_by_text("无法初始化",exact=False).wait_for()
                assert fallback.get_by_role("heading",name="交易工作台",exact=True).is_visible()
                network=browser.new_page();network.on("pageerror",lambda e:errors.append(str(e)))
                network.route("**/api/replay?*",lambda route:route.fulfill(status=400,json={"error":"验收故障注入：历史归档不可用"}))
                network.goto(url);network.get_by_role("button",name="开启图表回放",exact=True).click()
                network.get_by_role("alert").get_by_text("验收故障注入：历史归档不可用",exact=False).wait_for()
                # Isolated browser response fixture only: no database writes or broker calls.
                stress=copy.deepcopy(before);stress["state"].update(t=START+99999,deadline=START+100999,latest="合成压力测试，非真实资产")
                stress["state"]["config"].update(source="public",capital=10)
                stress["curve"]=[[START+i,10+i*.0001] for i in range(100000)]
                calls=[0]
                def respond(route):
                    calls[0]+=1;stress["curve"][-1][1]=20+calls[0]
                    route.fulfill(json=stress)
                pressure=browser.new_page(viewport={"width":1366,"height":768});pressure.on("pageerror",lambda e:errors.append(str(e)))
                pressure.route("**/api/state*",respond)
                started=time.perf_counter();pressure.goto(url);pressure.locator('[data-chart-points="86401"]').wait_for(timeout=15000)
                pressure.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                elapsed=(time.perf_counter()-started)*1000;assert elapsed<5000,elapsed
                pressure.evaluate("window.originalCanvas=document.querySelector('[data-chart-points] canvas')")
                value=pressure.locator('[data-chart-last]').get_attribute('data-chart-last')
                pressure.wait_for_function("v=>document.querySelector('[data-chart-last]').dataset.chartLast!==v",arg=value,timeout=7000)
                assert pressure.evaluate("window.originalCanvas===document.querySelector('[data-chart-points] canvas')")
                assert not errors,errors
                result=dict(browser_version=browser.version,canvas_failure_fallback=True,replay_network_error=True,archive_minutes=1440,ledger_fills=count,replay_read_only=True,synthetic_input_points=100000,visible_points=86401,first_render_ms=elapsed,render_budget_ms=5000,poll_updates=calls[0],page_errors=errors)
                (out/'replay-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                for tab in (pressure,page,fallback,network):tab.goto('about:blank')
                browser.close()
            print(json.dumps(result))
        finally:proc.terminate();proc.wait(15)


if __name__=="__main__":serve() if "--serve" in sys.argv else run()
