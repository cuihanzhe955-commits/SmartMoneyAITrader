"""Read-only event research UI, temporary runtime and explicitly synthetic metadata."""
import os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def serve():
    import uvicorn
    import json
    from datetime import datetime,timezone,timedelta
    from unittest.mock import patch
    from test_event_research import market
    from test_event_details import book,resolved
    from market.event_details import ENDPOINT,BOOK,FEE,RESOLUTION
    from test_event_costs import info
    from market.event_costs import CLOB_INFO
    from terminal.api import create_app
    class ModelMock:
        def __init__(self,c,key):self.c=c
        def chat(self,prompt,data):
            if "observation" in prompt:return json.dumps(dict(observation="合成验收结果",hypothesis="仅供测试，不能证明策略有效",invalidation="样本外不成立"))
            return json.dumps(dict(action="BUY",probability=.9,reason="合成验收假设",counter_evidence="未校准"))
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):
                raise RuntimeError("Event browser forbids external connections")
    sys.addaudithook(guard)
    def fetch(params):
        if params.get("slug")=="error":raise ValueError("测试替身：公开接口限频")
        data=market();data.update(version="v1",feesEnabled=True,endDate=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat());data["closed"]=params.get("closed")=="true";data["question"]="合成验收市场 · <script>window.fixtureInjected=true</script>"
        if params.get("slug"):data["slug"]=params["slug"]
        if params.get("slug")=="slow":time.sleep(.6)
        return [data]
    def details(url,params):
        if url==ENDPOINT+"/1":
            data=market();data.update(version="v1",feesEnabled=True,endDate=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat());return data
        if url==CLOB_INFO+book()["market"]:return info()
        if url==BOOK:
            data=book();data.update(timestamp=str(int(time.time()*1000)),asset_id=params["token_id"])
            return data
        if url==FEE:return dict(base_fee=30)
        if url==RESOLUTION:
            time.sleep(.03)
            data=resolved();data['data'][0].update(resolved_at=str(time.time()-.001),last_update_timestamp=str(time.time()-.001));return data
        raise AssertionError("Unexpected endpoint")
    with patch("market.predictions.public_page",side_effect=fetch),patch("market.event_details.public_get",side_effect=details),patch("terminal.api.Provider",ModelMock):
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
                errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
                page.goto(url);aside=page.locator("aside");aside.get_by_role("button",name="实验功能",exact=True).click();aside.get_by_role("button",name="策略实验室",exact=True).click()
                panel=page.locator("[data-event-research]");panel.get_by_text("尚未查询事件市场",exact=False).wait_for();button=panel.get_by_role("button",name="查询 Polymarket 公开市场",exact=True);button.click();panel.get_by_text("显示 1 个二元市场",exact=False).wait_for();assert page.evaluate("window.fixtureInjected") is None
                panel.get_by_role("button",name="查看市场标识",exact=True).click();dialog=page.get_by_role("dialog");dialog.get_by_text("condition_id",exact=False).wait_for();page.keyboard.press("Escape");panel.get_by_role("button",name="查询公开详情",exact=True).click();details_panel=page.locator("[data-event-details='1']");details_panel.get_by_role("button",name="读取盘口与基准费率",exact=True).click();details_panel.locator("[data-event-quote]").get_by_text("已核验双边盘口快照",exact=False).wait_for();details_panel.locator("[data-event-quote]").get_by_text("结果 Down",exact=False).wait_for();details_panel.get_by_text("费用曲线与逐档成本研究",exact=True).click();details_panel.get_by_role("button",name="计算公开盘口成本",exact=True).click();details_panel.locator("[data-event-cost]").get_by_text("模型合计",exact=False).wait_for();details_panel.get_by_role("button",name="保存研究记录",exact=True).click();history=panel.locator("[data-event-observations]");history.get_by_text("共 1 条",exact=False).wait_for();details_panel.get_by_role("button",name="查询官方结算",exact=True).click();details_panel.locator("[data-event-resolution]").get_by_text("官方接口结算证据已核验",exact=False).wait_for();assert not errors,errors;page.goto("about:blank");browser.close()
            print("PASS event UI navigation: experiment menu opens strategy lab")
        finally:proc.terminate();proc.wait(15)


if __name__=="__main__":serve() if "--serve" in sys.argv else run()
