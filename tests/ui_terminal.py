import json
import os
import sys
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run():
    out = ROOT / "tests" / "screenshots"
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "terminal.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "18786",
                "--log-level",
                "error",
            ],
            env=dict(os.environ, SMART_MONEY_RUNTIME=tmp),
            cwd=ROOT,
        )
        try:
            for _ in range(120):
                try:
                    urlopen("http://127.0.0.1:18786/api/health", timeout=0.5)
                    break
                except OSError:
                    time.sleep(0.1)
            with sync_playwright() as pw:
                b = pw.chromium.launch(channel="chrome")
                p = b.new_page(viewport={"width": 1366, "height": 768})
                errors = []
                p.on("pageerror", lambda e: errors.append(str(e)))
                p.on("dialog", lambda d: d.accept())
                p.goto("http://127.0.0.1:18786")
                p.get_by_role("button", name="配置普通交易").click()
                p.get_by_label("历史市场回放倍率").select_option("3600")
                p.get_by_label("已确认账户").check()
                p.get_by_role("button", name="创建会话").click()
                p.get_by_role("button", name="开始运行").click()
                p.wait_for_function("document.body.innerText.includes('运行中')")
                time.sleep(3)
                p.get_by_role("button", name="暂停", exact=True).click()
                p.get_by_role("button", name="恢复", exact=True).wait_for()
                for w, h in ((1366, 768), (1920, 1080)):
                    p.set_viewport_size(dict(width=w, height=h))
                    for n in (
                        "总览",
                        "市场雷达",
                        "决策中心",
                        "自动交易",
                        "持仓与资产",
                        "交易流水",
                        "历史回测",
                        "设置",
                    ):
                        p.locator("aside").get_by_role(
                            "button", name=n, exact=True
                        ).click()
                        p.wait_for_timeout(220)
                        assert p.evaluate(
                            "document.documentElement.scrollWidth<=innerWidth"
                        ), (w, n)
                        p.screenshot(path=str(out / f"{n}-{w}.png"))
                    p.locator("aside").get_by_role("button", name="决策中心").click()
                    p.locator("tbody tr").first.click()
                    p.get_by_role("dialog").wait_for()
                    p.screenshot(path=str(out / f"交易详情-{w}.png"))
                    p.get_by_label("关闭", exact=True).click()
                p.locator("aside").get_by_role("button", name="总览").click()
                p.get_by_role("button", name="结束", exact=True).click()
                p.locator("aside").get_by_role("button", name="实验报告").click()
                p.get_by_role("link", name="JSON").wait_for()
                p.locator("aside").get_by_role("button", name="策略实验室").click()
                p.get_by_role("button", name="使用挑战模板").click()
                p.get_by_label("已确认账户").check()
                p.screenshot(path=str(out / "挑战创建.png"))
                p.get_by_role("button", name="创建会话").click()
                p.get_by_role("button", name="开始运行").click()
                p.locator("aside").get_by_role("button", name="自动交易").click()
                for w, h in ((1366, 768), (1920, 1080)):
                    p.set_viewport_size(dict(width=w, height=h))
                    p.wait_for_timeout(400)
                    p.screenshot(path=str(out / f"挑战-{w}.png"))
                p.get_by_role("button", name="紧急停止", exact=True).click()
                p.get_by_label("切换主题").click()
                assert p.locator("body.light").count()
                b.close()
                assert not errors, errors
                print(
                    "PASS browser: 12 navigation sections, session setup, controls, journal, report and viewport screenshots"
                )
        finally:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    run()
