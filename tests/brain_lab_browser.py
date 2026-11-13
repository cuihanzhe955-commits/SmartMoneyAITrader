"""Real browser, temporary runtime, explicitly synthetic market + ModelMock.

Uses the same network-forbidden fixture server as event_research_browser.
"""
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
                # Configure only synthetic credentials in the temporary vault.
                r=page.request.post(url+'/api/ai',data={'config':{'base':'https://fixture.invalid/v1','model':'model-mock','timeout':5,'interval':30,'calls':40,'ttl':30,'fallback':'rules'},'key':'synthetic-model-fixture'})
                assert r.status==200,r.text()
                page.locator('aside').get_by_role('button',name='实验功能',exact=True).click();page.locator('aside').get_by_role('button',name='策略实验室',exact=True).click()
                brain=page.locator('[data-brain]');brain.get_by_text('已记录 0 条',exact=False).wait_for()
                brain.get_by_label('后续决策引用记忆',exact=True).check()
                discovery=page.locator('[data-event-research]');discovery.get_by_role('button',name='查询 Polymarket 公开市场',exact=True).click()
                discovery.get_by_role('button',name='用于预测研究',exact=True).click()
                lab=page.locator('[data-event-lab]');lab.get_by_text('创建独立研究会话',exact=True).click()
                lab.get_by_label('研究会话名称',exact=True).fill('合成F阶段验收')
                lab.get_by_label('研究决策引擎',exact=True).select_option('ai')
                lab.get_by_text('使用同会话的历史记忆',exact=False).locator('input').check()
                lab.get_by_text('保存有/无记忆的配对预测',exact=False).locator('input').check()
                lab.get_by_role('button',name='创建参考模拟会话',exact=True).click()
                lab.get_by_text('可用参考现金',exact=False).wait_for()
                assert lab.get_by_label('研究市场ID',exact=True).input_value()=='1'
                lab.get_by_label('研究目标份额',exact=True).fill('20')
                lab.get_by_role('button',name='提交一轮预测研究',exact=True).click()
                lab.get_by_text('已结算 / 参考模拟买入',exact=False).wait_for(timeout=20000)
                lab.get_by_role('button',name='查看配对评估',exact=True).click()
                lab.locator('[data-event-evaluation]').get_by_text('完整配对 1 轮',exact=False).wait_for()
                lab.get_by_role('button',name='查看轮次证据',exact=True).click()
                page.get_by_role('dialog').get_by_text('snapshot_sha256',exact=False).wait_for();page.keyboard.press('Escape')
                brain.get_by_role('button',name='搜索 / 刷新记忆',exact=True).click()
                brain.get_by_role('button',name='查看记忆来源',exact=True).first.wait_for()
                brain.get_by_role('button',name='纠错 / 标记失效',exact=True).first.click()
                brain.get_by_label('纠错说明',exact=True).fill('合成纠错验收，不用于真实交易')
                brain.get_by_label('停止后续引用此条记忆',exact=True).check()
                brain.get_by_role('button',name='保存记忆纠错',exact=True).click()
                brain.get_by_text('已失效 / v2',exact=False).wait_for()
                with page.expect_download() as event:brain.get_by_role('button',name='导出记忆备份',exact=True).click()
                backup=out/'synthetic-brain-backup.json';event.value.save_as(backup)
                brain.get_by_label('恢复记忆备份',exact=True).set_input_files(backup)
                page.wait_for_timeout(400)
                assert not brain.get_by_role('alert').count()
                for w,h in ((1366,768),(1920,1080)):
                    page.set_viewport_size({'width':w,'height':h})
                    for theme in ('dark','light'):
                        if page.evaluate("document.body.classList.contains('light')")!=(theme=='light'):page.get_by_label('切换主题').click()
                        for name,panel in (('lab',lab),('brain',brain)):
                            panel.scroll_into_view_if_needed()
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            page.screenshot(path=str(out/f'{name}-{w}-{theme}.png'))
                lab.get_by_role('button',name='暂停新预测',exact=True).click()
                lab.get_by_text('环境：参考模拟 · 已暂停',exact=False).wait_for()
                assert lab.get_by_role('button',name='提交一轮预测研究',exact=True).is_disabled()
                page.reload();page.locator('aside').get_by_role('button',name='实验功能',exact=True).click();page.locator('aside').get_by_role('button',name='策略实验室',exact=True).click()
                page.locator('[data-event-lab]').get_by_label('当前研究会话',exact=True).select_option(index=1)
                page.locator('[data-event-lab]').get_by_text('已结算 / 参考模拟买入',exact=False).wait_for()
                assert page.request.get(url+'/api/state').json()['state'] is None
                assert not errors,errors
                browser.close()
            print('PASS F browser: ModelMock paired prediction, reference fill/settlement, evaluation, memory correction/export/restore, pause and reload; 2 sizes x 2 themes; no live session')
        finally:proc.terminate();proc.wait(15)


if __name__=='__main__':run()
