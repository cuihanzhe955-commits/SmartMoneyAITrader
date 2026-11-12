"""Archive-backed research UI and paused chart regression; no exchange accounts."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def serve():
    import uvicorn
    from terminal.api import create_app
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):
                raise RuntimeError("research test prohibits external network")
    sys.addaudithook(guard)
    uvicorn.run(create_app(),host="127.0.0.1",port=int(sys.argv[2]),log_level="error")


def run():
    from playwright.sync_api import sync_playwright
    from terminal.runtime import Runtime
    from terminal.config import Session
    from challenge.manager import scan
    from market.feeds import START,historical
    out=Path(os.environ["SMART_MONEY_UI_OUTPUT"]);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        rt=Runtime(temp)
        with rt.db.db:
            s=rt.new(Session(consent=True));rt.command(s["id"],"start")
            s=rt.db.load()
            for minute in range(181):scan(rt.db,s,START+minute*60,historical(START+minute*60))
            rt.db.save(s);rt.command(s["id"],"pause")
            assert rt.db.entries("fills",s["id"])
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
                browser=p.chromium.launch(channel="chrome");page=browser.new_page(viewport={"width":1366,"height":768})
                errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
                page.goto(url);page.locator("aside").get_by_role("button",name="实验功能",exact=True).click()
                page.locator("[data-chart-points]").wait_for()
                assert int(page.locator("[data-chart-markers]").first.get_attribute("data-chart-markers"))>0
                page.get_by_label("切换主题").click()
                page.locator('[data-chart-theme="light"]').wait_for()
                # Same row count and session time; only an isolated NAV snapshot changes.
                # This is explicitly a rendering fault fixture, not a real balance.
                chart=page.locator("[data-chart-last]").first
                before=float(chart.get_attribute("data-chart-last"));target=before+1
                with closing(sqlite3.connect(Path(temp)/"terminal.db")) as db,db:
                    row=db.execute("SELECT id,data FROM portfolio_snapshots ORDER BY id DESC LIMIT 1").fetchone()
                    value=json.loads(row[1]);value["nav"]=target;db.execute("UPDATE portfolio_snapshots SET data=? WHERE id=?",(json.dumps(value),row[0]))
                page.wait_for_function("t => Number(document.querySelector('[data-chart-last]').getAttribute('data-chart-last'))===t",arg=target,timeout=12000)
                page.screenshot(path=str(out/"paused-chart-update.png"),full_page=True)
                page.locator("aside").get_by_role("button",name="策略实验室",exact=True).click()
                page.get_by_role("heading",name="指标口径研究",exact=True).wait_for()
                page.get_by_text("RSI 14",exact=True).wait_for()
                page.get_by_label("指标研究币种").select_option("ETH")
                page.get_by_label("指标研究时点").select_option("360")
                page.get_by_text("当前执行口径仍为原策略。",exact=False).wait_for()
                with page.expect_download() as download:page.get_by_role("button",name="导出指标对照报告",exact=True).click()
                assert download.value.suggested_filename=="indicator-research-ETH.json"
                payload=json.loads(Path(download.value.path()).read_text())
                assert payload["symbol"]=="ETH" and payload["as_of"]==START+360*60 and not payload["engine_changed"]
                for width,height in [(1366,768),(1920,1080)]:
                    page.set_viewport_size({"width":width,"height":height})
                    for theme in ("dark","light"):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=="light"):page.get_by_label("切换主题").click()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.screenshot(path=str(out/("indicator-"+str(width)+"-"+theme+".png")),full_page=True)
                data=page.request.get(url+"/api/state").json()["state"]
                assert data["lifecycle_status"]=="PAUSED" and data["config"]["engine"]=="rules"
                assert not errors,errors
                for context in browser.contexts:
                    for tab in context.pages:tab.goto("about:blank")
                browser.close()
            print("PASS archive indicator research, JSON export, paused theme and same-length chart update; 2 sizes x 2 themes")
        finally:proc.terminate();proc.wait(15)


if __name__=="__main__":serve() if "--serve" in sys.argv else run()
