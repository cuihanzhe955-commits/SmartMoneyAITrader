"""Browser checks for G1 using temporary runtime and explicit ModelMock sources."""
import os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def run():
    from playwright.sync_api import sync_playwright
    out=Path(os.environ['SMART_MONEY_UI_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        proc=subprocess.Popen([sys.executable,'-X','utf8','-B',str(ROOT/'tests/event_research_browser.py'),'--serve',str(port)],cwd=ROOT,env={**os.environ,'SMART_MONEY_RUNTIME':temp})
        try:
            for _ in range(100):
                try:
                    with urlopen(url+'/api/health',timeout=1):break
                except OSError:time.sleep(.1)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='chrome');page=browser.new_page(viewport={'width':1366,'height':768})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url)
                assert page.request.post(url+'/api/ai',data={'config':{'base':'https://fixture.invalid/v1','model':'ModelMock','timeout':5,'interval':30,'calls':40,'ttl':30,'fallback':'rules'},'key':'synthetic-model-fixture'}).status==200
                page.locator('aside').get_by_role('button',name='策略实验室',exact=True).click()
                panel=page.locator('[data-prediction-challenge]');panel.get_by_text('尚未创建自动预测挑战。',exact=True).wait_for()
                panel.get_by_text('创建并启动自动挑战',exact=True).click()
                panel.get_by_label('挑战名称',exact=True).fill('合成G1浏览器验收')
                panel.get_by_label('目标有效轮次',exact=True).fill('1')
                panel.get_by_role('button',name='创建并启动预测挑战',exact=True).click()
                panel.get_by_text('目标完成 · AI预测 · 有效完成 1 / 1 轮',exact=False).wait_for(timeout=25000)
                assert panel.get_by_role('progressbar').get_attribute('value')=='1'
                panel.get_by_role('button',name='查看挑战轮次',exact=True).click()
                page.get_by_role('dialog').get_by_text('snapshot_sha256',exact=False).wait_for();page.keyboard.press('Escape')
                with page.expect_download() as download:panel.get_by_role('button',name='导出挑战报告',exact=True).click()
                download.value.save_as(out/'synthetic-challenge-report.json')
                # An owned challenge cannot be selected for manual insertion.
                assert page.locator('[data-event-lab]').get_by_label('当前研究会话',exact=True).locator('option').count()==1
                for w,h in ((1366,768),(1920,1080)):
                    page.set_viewport_size({'width':w,'height':h})
                    for theme in ('dark','light'):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=='light'):page.get_by_label('切换主题').click()
                        panel.locator('[data-prediction-progress]').scroll_into_view_if_needed()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(out/f'challenge-{w}-{theme}.png'))
                # The fixture exposes one unique condition. A goal of two must
                # wait, never re-use it to fake a second completed round.
                panel.get_by_label('挑战名称',exact=True).fill('合成暂停恢复验收')
                panel.get_by_label('挑战引擎',exact=True).select_option('rules')
                panel.get_by_label('目标有效轮次',exact=True).fill('2')
                panel.get_by_role('button',name='创建并启动预测挑战',exact=True).click()
                panel.get_by_text('自动运行 · 规则基线',exact=False).wait_for()
                panel.get_by_role('button',name='暂停新轮次',exact=True).click()
                panel.get_by_text('已暂停 · 规则基线',exact=False).wait_for()
                panel.get_by_role('button',name='恢复挑战',exact=True).click()
                panel.get_by_text('自动运行 · 规则基线',exact=False).wait_for()
                panel.get_by_role('button',name='结束挑战',exact=True).click()
                panel.get_by_text('已结束 · 规则基线',exact=False).wait_for(timeout=15000)
                page.reload();page.locator('aside').get_by_role('button',name='策略实验室',exact=True).click()
                panel=page.locator('[data-prediction-challenge]');panel.get_by_label('查看预测挑战',exact=True).select_option(index=2)
                panel.get_by_text('目标完成 · AI预测 · 有效完成 1 / 1 轮',exact=False).wait_for()
                assert page.request.get(url+'/api/state').json()['state'] is None
                assert not errors,errors
                browser.close()
            print('PASS G1 UI: create, automatic ModelMock result, source evidence, report, exclusive session, pause/resume/stop, reload; 2 viewports x 2 themes; no live session')
        finally:proc.terminate();proc.wait(15)


if __name__=='__main__':run()
