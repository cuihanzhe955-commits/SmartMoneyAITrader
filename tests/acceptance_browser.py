"""Real UI + API + temporary SQLite; exchange reads use explicitly isolated fixtures."""
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
    from unittest.mock import patch
    from test_acceptance import health_venue
    from terminal.api import create_app
    # Patch transport only. Actual API, report generation and SQLite stay in use.
    from terminal.runtime import Runtime
    def fixture(self, config):
        assert str(self.root) == os.environ["SMART_MONEY_RUNTIME"]
        v = health_venue(self)
        def audit(state):
            if (self.root / "fail-fixture").exists():
                raise ValueError("自动化测试：专用账户余额不符")
            return {"dedicated_balance_match": True}
        v.audit.side_effect = audit
        self.venue = fixture.__get__(self)
        return v
    with patch.object(Runtime, "venue", fixture):
        def guard(event, args):
            if event in ("socket.connect", "socket.connect_ex", "socket.sendto"):
                address = args[-1]
                if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                    raise RuntimeError("UI 验收禁止外部连接")
        sys.addaudithook(guard)
        uvicorn.run(create_app(), host="127.0.0.1", port=int(sys.argv[2]), log_level="error")


def run():
    from playwright.sync_api import sync_playwright
    from terminal.runtime import Runtime
    from test_acceptance import remote
    out = ROOT / "docs" / "phaseC_ui"
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, socket.socket() as sock:
        rt=Runtime(tmp); remote(rt); rt.db.db.close()
        sock.bind(("127.0.0.1",0)); port=sock.getsockname()[1]; sock.close()
        url=f"http://127.0.0.1:{port}"
        proc=subprocess.Popen([sys.executable,"-B",__file__,"--serve",str(port)],cwd=ROOT,
                              env={**os.environ,"SMART_MONEY_RUNTIME":tmp})
        try:
            for _ in range(100):
                try:
                    with urlopen(url+"/api/health",timeout=1): break
                except OSError: time.sleep(.1)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel="chrome")
                p=browser.new_page(viewport={"width":1366,"height":768})
                errors=[]; p.on("pageerror",lambda e:errors.append(str(e)))
                p.goto(url)
                p.locator("aside").get_by_role("button",name="设置",exact=True).click()
                p.get_by_role("button",name="运行只读验收").click()
                p.get_by_role("status").filter(has_text="只读检查通过").wait_for()
                with p.expect_download() as download:
                    p.get_by_role("button",name="导出本机检查报告").click()
                assert download.value.suggested_filename.startswith("local-acceptance-")
                assert p.request.get(url+"/api/state").json()["state"]["lifecycle_status"] == "CREATED"
                for w,h in [(1366,768),(1920,1080)]:
                    p.set_viewport_size({"width":w,"height":h})
                    for theme in ("dark","light"):
                        if p.evaluate("document.body.classList.contains('light')") != (theme == "light"):
                            p.get_by_label("切换主题").click()
                        assert p.evaluate("document.body.classList.contains('light')") == (theme == "light")
                        p.evaluate("""() => {
                            let tag=document.getElementById('test-only');
                            if(!tag){tag=document.createElement('div');tag.id='test-only';document.body.append(tag)}
                            tag.textContent='自动化测试环境 · 交易所读取为 Mock · 未执行真实资金交易';
                            tag.style='position:fixed;bottom:0;right:0;z-index:1000;background:#1d3557;color:white;padding:4px';
                        }""")
                        assert p.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        p.screenshot(path=str(out/f"checks-{w}-{theme}.png"),full_page=True)
                Path(tmp,"fail-fixture").touch()
                p.get_by_role("button",name="运行只读验收").click()
                p.get_by_role("status").filter(has_text="存在阻断项").wait_for()
                p.reload()
                p.locator("aside").get_by_role("button",name="设置",exact=True).click()
                p.get_by_role("status").filter(has_text="存在阻断项").wait_for()
                assert p.get_by_text("自动化测试：专用账户余额不符",exact=True).is_visible()
                p.screenshot(path=str(out/"blocked.png"),full_page=True)
                assert not errors,errors
                browser.close()
            print("PASS actual UI/API: readiness, blocked balance, report download/reload; 2 sizes x 2 themes; no orders")
        finally:
            proc.terminate(); proc.wait(15)


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else run()
