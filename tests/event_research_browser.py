"""Read-only event research UI, temporary runtime and explicitly synthetic metadata."""
import os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def serve():
    import uvicorn
    from unittest.mock import patch
    from test_event_research import market
    from terminal.api import create_app
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):
                raise RuntimeError("Event browser forbids external connections")
    sys.addaudithook(guard)
    def fetch(params):
        if params.get("slug")=="error":raise ValueError("测试替身：公开接口限频")
        data=market();data["question"]="合成验收市场 · <script>window.fixtureInjected=true</script>"
        if params.get("slug"):data["slug"]=params["slug"]
        if params.get("slug")=="slow":time.sleep(.6)
        return [data]
    with patch("market.predictions.public_page",side_effect=fetch):
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
                page.goto(url);page.locator("aside").get_by_role("button",name="策略实验室",exact=True).click()
                panel=page.locator("[data-event-research]");panel.get_by_text("尚未查询事件市场",exact=False).wait_for()
                button=panel.get_by_role("button",name="查询 Polymarket 公开市场",exact=True);button.click()
                panel.get_by_text("显示 1 个二元市场",exact=False).wait_for()
                assert page.evaluate("window.fixtureInjected") is None
                panel.get_by_role("button",name="查看市场标识",exact=True).click()
                dialog=page.get_by_role("dialog");dialog.get_by_text("condition_id",exact=False).wait_for()
                page.screenshot(path=str(out/"event-identities.png"),full_page=True);page.keyboard.press("Escape")
                for w,h in ((1366,768),(1920,1080)):
                    page.set_viewport_size({"width":w,"height":h})
                    for theme in ("dark","light"):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=="light"):page.get_by_label("切换主题").click()
                        panel.scroll_into_view_if_needed()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.screenshot(path=str(out/f"events-{w}-{theme}.png"))
                page.get_by_label("事件标题关键词",exact=True).fill("no-match");button.click()
                panel.get_by_text("显示 0 个二元市场",exact=False).wait_for()
                page.get_by_label("事件标题关键词",exact=True).fill("")
                page.get_by_label("事件市场 slug",exact=True).fill("slow");button.click()
                panel.get_by_role("button",name="正在读取事件市场…",exact=True).wait_for()
                assert page.request.get(url+"/api/health").status==200
                panel.get_by_text("显示 1 个二元市场",exact=False).wait_for()
                page.get_by_label("事件市场 slug",exact=True).fill("error");button.click()
                panel.get_by_role("alert").get_by_text("限频",exact=False).wait_for()
                page.screenshot(path=str(out/"events-error.png"))
                assert page.request.get(url+"/api/state").json()["state"] is None
                assert not errors,errors
                page.goto("about:blank");browser.close()
            print("PASS event UI: inert text, full identities, 2 viewports x 2 themes, empty/loading/error, no session mutation")
        finally:proc.terminate();proc.wait(15)


if __name__=="__main__":serve() if "--serve" in sys.argv else run()
