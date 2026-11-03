"""Browser acceptance in an isolated runtime. No exchange orders or credentials."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from challenge.manager import decision
from events.store import Store
from market.feeds import START, historical
from risk.limits import allowance
from strategy.rules import analyze


def run():
    output = ROOT / "upgrade_review" / "phase3_screenshots"
    output.mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "uvicorn", "terminal.api:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
            cwd=ROOT, env={**os.environ, "SMART_MONEY_RUNTIME": tmp, "PYTHONIOENCODING": "utf-8"},
        )
        try:
            for _ in range(100):
                try:
                    with urlopen(url + "/api/health", timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                page = browser.new_page(viewport={"width": 1366, "height": 768})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", lambda route: route.continue_()
                           if route.request.url.startswith(url + "/") else route.abort())
                page.goto(url)
                page.get_by_role("button", name="配置普通交易").click()
                page.get_by_label("单笔目标 / 净资产 %", exact=True).fill("80")
                page.get_by_label("单笔风险预算 / 净资产 %", exact=True).fill("3")
                page.get_by_text("超出推荐范围，保留你的选择", exact=True).wait_for()
                page.get_by_label("单笔风险预算 / 净资产 %", exact=True).fill("0.5")
                page.get_by_text("策略与执行参数", exact=True).click()
                page.get_by_label("单币上限 / 净资产 %", exact=True).fill("90")
                for w, h in ((1366, 768), (1920, 1080)):
                    page.set_viewport_size({"width": w, "height": h})
                    for theme in ("dark", "light"):
                        if bool(page.locator("body.light").count()) != (theme == "light"):
                            page.get_by_label("切换主题", exact=True).click()
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.screenshot(path=str(output / f"builder-{w}-{theme}.png"), full_page=True)
                page.get_by_label("已确认账户").check()
                page.get_by_role("button", name="创建会话").click()
                page.get_by_role("button", name="开始运行", exact=True).wait_for()
                # Insert a labeled explanation fixture, without starting the session.
                db = Store(Path(tmp) / "terminal.db")
                with db.db:
                    s = db.load()
                    assert s["config"]["risk_per_trade_pct"] == 0.5
                    assert s["config"]["target"] == 80
                    assert s["config"]["execution"] == "paper"
                    assert s["lifecycle_status"] == "CREATED"
                    m = analyze(historical(START)["BTC"], START, s["config"])
                    m["score"] = 70
                    amount, why, caps = allowance(s, s["config"], m)
                    decision(db, s, "BTC", m, "BUY", "界面计算展示样本，未提交委托",
                             amount, caps["calculation"])
                db.db.close()
                page.locator("aside").get_by_role("button", name="决策中心", exact=True).click()
                page.locator("tbody tr").first.click()
                page.get_by_text("仓位计算明细", exact=True).wait_for()
                for w, h in ((1366, 768), (1920, 1080)):
                    page.set_viewport_size({"width": w, "height": h})
                    page.screenshot(path=str(output / f"sizing-{w}.png"))
                assert page.get_by_role("dialog").inner_text().count("风险预算") > 0
                assert not errors, errors
                browser.close()
                print("PASS browser configuration preservation, sizing details, two viewports and themes")
        finally:
            proc.terminate()
            proc.wait(timeout=15)


if __name__ == "__main__":
    run()
