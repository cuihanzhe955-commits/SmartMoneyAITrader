"""Playwright smoke tests. Separate temporary database and server."""

import os
import sys
import tempfile
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/screenshots"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "server.py"),
                "--port",
                "18784",
                "--db",
                str(Path(tmp) / "qa.db"),
            ]
        )
        try:
            for _ in range(50):
                try:
                    urlopen("http://127.0.0.1:18784/api/state", timeout=0.5)
                    break
                except OSError:
                    time.sleep(0.1)
            with sync_playwright() as pw:
                chrome = (
                    Path(os.getenv("PROGRAMFILES", ""))
                    / "Google/Chrome/Application/chrome.exe"
                )
                browser = pw.chromium.launch(
                    executable_path=str(chrome) if chrome.exists() else None
                )
                p = browser.new_page(viewport={"width": 1366, "height": 768})
                errors = []
                external = []
                p.on("pageerror", lambda e: errors.append(str(e)))
                p.on(
                    "request",
                    lambda r: (
                        external.append(r.url)
                        if not r.url.startswith(("http://127.0.0.1", "data:"))
                        else None
                    ),
                )
                p.goto("http://127.0.0.1:18784")
                p.locator("#setup").wait_for()
                p.screenshot(path=str(out / "01-setup-1366.png"), full_page=True)
                p.locator("button[type=submit]").click()
                assert p.locator("#setup").count()
                p.locator("[name=speed]").select_option("3600")
                p.locator("[name=consent]").check()
                p.locator("button[type=submit]").click()
                p.locator("[data-act=start]").click()
                p.wait_for_function(
                    "document.querySelector('.feed')?.innerText.includes('HOLD')",
                    timeout=30000,
                )
                time.sleep(1.5)
                p.locator("[data-act=pause]").click()
                p.locator("[data-act=resume]").wait_for()
                p.locator("[data-act=zoom]").click()
                for w, h in [(1366, 768), (1920, 1080)]:
                    p.set_viewport_size({"width": w, "height": h})
                    assert p.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    )
                    p.screenshot(path=str(out / f"02-terminal-{w}.png"), full_page=True)
                p.locator("[data-act=assets]").click()
                assert p.locator("dialog").is_visible()
                p.locator("#close").click()
                p.locator("#kind").select_option("HOLD")
                p.locator('[data-event="0"]').click()
                p.locator("#close").click()
                p.locator("[data-act=resume]").click()
                p.locator("[data-act=pause]").wait_for()
                p.locator("[data-act=decisions]").click()
                p.locator("[data-act=record0]").click()
                p.locator("#close").click()
                p.locator("[data-act=end]").click()
                p.locator("[data-act=confirmend]").click()
                p.locator("[data-act=report]").wait_for()
                for fmt in ("html", "csv", "json"):
                    resp = p.request.get("http://127.0.0.1:18784/export/" + fmt)
                    assert resp.ok and len(resp.body()) > 100
                p.locator("[data-nav=history]").click()
                p.locator("[data-act=open1]").click()
                p.locator("[data-act=report]").click()
                p.locator("#close").click()
                p.locator("[data-act=new]").click()
                p.locator("[data-act=amount20]").click()
                p.locator("[data-act=preset快速动量]").click()
                p.locator("[name=consent]").check()
                p.locator("button[type=submit]").click()
                p.locator("[data-act=start]").click()
                p.locator("[data-act=stop]").click()
                p.locator("[data-act=confirmstop]").click()
                p.locator("[data-act=report]").wait_for()
                state = p.request.get("http://127.0.0.1:18784/api/state").json()[
                    "state"
                ]
                assert (
                    state["lifecycle_status"] == "STOPPED"
                    and state["config"]["capital"] == 20
                )
                p.locator("header [data-nav=overview]").click()
                p.get_by_role("heading", name="工作台总览").wait_for()
                assert not errors and not external, (errors, external)
                browser.close()
                print(
                    "PASS Playwright setup, controls, filters, report, export, history and responsive layout"
                )
        finally:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    run()
