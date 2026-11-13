"""Verify template navigation and real paper-session lifecycle in an isolated runtime."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]


def serve(port):
    import uvicorn
    def guard(event,args):
        if event in ("socket.connect","socket.connect_ex","socket.sendto"):
            address=args[-1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):
                raise RuntimeError("模板验收禁止外部连接")
    sys.addaudithook(guard)
    uvicorn.run("terminal.api:app",host="127.0.0.1",port=port,log_level="error")


def run():
    from playwright.sync_api import sync_playwright
    output=ROOT/"docs"/"challenge_template_ui"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, socket.socket() as sock:
        sock.bind(("127.0.0.1",0)); port=sock.getsockname()[1]; sock.close()
        url=f"http://127.0.0.1:{port}"
        proc=subprocess.Popen([sys.executable,"-B",__file__,"--serve",str(port)],cwd=ROOT,
            env={**os.environ,"SMART_MONEY_RUNTIME":tmp,"PYTHONIOENCODING":"utf-8"})
        try:
            for _ in range(100):
                try:
                    with urlopen(url+"/api/health",timeout=1): break
                except OSError: time.sleep(.1)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel="chrome")
                p=browser.new_page(viewport={"width":1366,"height":768})
                errors=[]; posts=[]
                p.on("pageerror",lambda e:errors.append(str(e)))
                p.on("request",lambda r:posts.append(r.post_data_json)
                     if r.method=="POST" and r.url==url+"/api/sessions" else None)
                p.on("dialog",lambda d:d.accept())
                p.goto(url);p.locator("aside").get_by_role("button",name="实验功能",exact=True).click()
                side=p.locator("aside")
                assert side.get_by_role("button",name="24小时翻倍挑战",exact=True).count()==0
                side.get_by_role("button",name="策略实验室",exact=True).click()
                p.get_by_role("heading",name="策略模板",exact=True).wait_for()
                for w,h in [(1366,768),(1920,1080)]:
                    p.set_viewport_size({"width":w,"height":h})
                    for theme in ("dark","light"):
                        if p.evaluate("document.body.classList.contains('light')") != (theme=="light"):
                            p.get_by_label("切换主题").click()
                        assert p.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        p.screenshot(path=str(output/f"templates-{w}-{theme}.png"))
                p.get_by_role("button",name="使用挑战模板").click()
                selector=p.get_by_label("策略模板",exact=True)
                assert selector.input_value()=="challenge"
                assert p.get_by_label("初始模拟本金 · USDT",exact=True).input_value()=="10"
                assert p.get_by_label("02 · 决策引擎").locator("option").all_text_contents()==["规则引擎"]
                # Merely choosing a template never creates a session or carries live authority.
                p.get_by_label("01 · 执行环境").select_option("live")
                p.get_by_label("真实资金确认").fill("启用实盘")
                p.get_by_label("已确认账户").check()
                selector.select_option("normal")
                assert p.get_by_label("01 · 执行环境").input_value()=="paper"
                assert not p.get_by_label("已确认账户").is_checked()
                assert p.get_by_label("真实资金确认").count()==0
                assert p.get_by_label("02 · 决策引擎").locator("option").all_text_contents()==["规则引擎","AI 增强"]
                selector.select_option("challenge")
                assert not posts
                p.get_by_label("历史市场回放倍率").select_option("1")
                p.screenshot(path=str(output/"challenge-form.png"),full_page=True)
                p.get_by_label("已确认账户").check()
                p.get_by_role("button",name="创建会话",exact=False).click()
                p.get_by_role("button",name="开始运行",exact=True).wait_for()
                assert len(posts)==1 and posts[0]["profile"]=="challenge" and posts[0]["engine"]=="rules"
                current=p.request.get(url+"/api/state").json()
                sid=current["state"]["id"]
                assert current["state"]["lifecycle_status"]=="CREATED" and not current["fills"]
                side.get_by_role("button",name="运行",exact=True).click()
                assert p.get_by_text("24H DOUBLE CHALLENGE",exact=False).is_visible()
                assert selector.count()==0
                # Existing challenge remains accessible and cannot be replaced through a template.
                side.get_by_role("button",name="策略实验室",exact=True).click()
                p.get_by_role("button",name="使用普通模板").click()
                p.get_by_role("button",name="开始运行",exact=True).wait_for()
                assert len(posts)==1 and p.request.get(url+"/api/state").json()["state"]["id"]==sid
                p.get_by_role("button",name="开始运行",exact=True).click()
                p.get_by_role("button",name="暂停",exact=True).wait_for()
                p.get_by_role("button",name="暂停",exact=True).click()
                p.get_by_role("button",name="恢复",exact=True).wait_for()
                p.screenshot(path=str(output/"challenge-workbench.png"))
                p.reload();p.locator("aside").get_by_role("button",name="实验功能",exact=True).click()
                side.get_by_role("button",name="运行",exact=True).click()
                p.get_by_role("button",name="恢复",exact=True).wait_for()
                assert p.request.get(url+"/api/state").json()["state"]["id"]==sid
                p.get_by_role("button",name="结束",exact=True).click()
                p.get_by_role("button",name="新建会话",exact=True).wait_for()
                old=p.request.get(url+"/api/state?id="+str(sid)).json()
                assert old["report"] and old["state"]["config"]["profile"]=="challenge"
                # The normal template also creates an independent, stopped draft session.
                side.get_by_role("button",name="策略实验室",exact=True).click()
                p.get_by_role("button",name="使用普通模板").click()
                assert selector.input_value()=="normal"
                p.get_by_label("已确认账户").check()
                p.get_by_role("button",name="创建会话",exact=False).click()
                p.get_by_role("button",name="开始运行",exact=True).wait_for()
                normal=p.request.get(url+"/api/state").json()
                assert normal["state"]["id"]!=sid and normal["state"]["config"]["profile"]=="normal"
                assert normal["state"]["lifecycle_status"]=="CREATED"
                assert len(normal["archive"])==2 and len(posts)==2
                assert p.request.get(url+"/api/state?id="+str(sid)).json()["report"]==old["report"]
                assert not errors,errors
                browser.close()
            print("PASS template navigation/selector; live confirmation reset; no auto-start; challenge start/pause/reload/end/report; existing-session guard; independent ordinary session; 4 visual screenshots; no real orders")
        finally:
            proc.terminate();proc.wait(15)


if __name__=="__main__":
    sys.path.insert(0,str(ROOT))
    serve(int(sys.argv[2])) if "--serve" in sys.argv else run()
