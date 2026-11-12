"""Exercise Phase 4 UI against a private, temporary Windows runtime."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/"docs"/"phase4_ui"
out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as tmp, socket.socket() as sock:
    sock.bind(("127.0.0.1",0))
    port=sock.getsockname()[1]
    sock.close()
    url=f"http://127.0.0.1:{port}"
    proc=subprocess.Popen([sys.executable,"-B","-m","uvicorn","terminal.api:app","--host","127.0.0.1",
                           "--port",str(port),"--log-level","error"],cwd=ROOT,env={**os.environ,"SMART_MONEY_RUNTIME":tmp})
    try:
        for _ in range(100):
            try:
                with urlopen(url+"/api/health",timeout=1):break
            except OSError:time.sleep(.1)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel="chrome")
            p=browser.new_page(viewport={"width":1366,"height":768})
            errors=[]
            p.on("pageerror",lambda e:errors.append(str(e)))
            p.goto(url);p.locator("aside").get_by_role("button",name="实验功能",exact=True).click()
            p.locator("aside").get_by_role("button",name="设置",exact=True).click()
            field=p.get_by_label("故障策略")
            field.select_option("manual")
            p.get_by_label("模型",exact=True).fill("fixture")
            p.get_by_label("服务密钥").fill("ui-fixture")
            p.get_by_role("button",name="保存 AI 配置").click()
            p.wait_for_function("fetch('/api/settings').then(r=>r.json()).then(x=>x.ai.fallback==='manual')")
            field.scroll_into_view_if_needed()
            p.screenshot(path=str(out/"settings.png"))
            p.locator("aside").get_by_role("button",name="策略实验室").click()
            p.get_by_role("button",name="使用挑战模板").click()
            engine=p.get_by_label("02 · 决策引擎")
            assert engine.locator("option").all_text_contents()==["规则引擎"]
            p.set_viewport_size({"width":1920,"height":1080})
            p.get_by_label("切换主题").click()
            assert p.evaluate("document.documentElement.scrollWidth<=innerWidth")
            p.screenshot(path=str(out/"challenge.png"))
            assert not errors,errors
            browser.close()
            print("PASS manual fallback saved in isolated backend; rule-only challenge; 1366 and 1920 screenshots")
    finally:
        proc.terminate()
        proc.wait(15)

