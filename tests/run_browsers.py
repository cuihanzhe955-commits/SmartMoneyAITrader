"""Windows browser acceptance: owned child trees, separate logs, fail on any suite."""
import datetime,json,os,socket,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from windows_instance import Job
root=Path(__file__).resolve().parents[1];os.chdir(root)
out=Path(os.environ.get('SMART_MONEY_BROWSER_LOGS',root/'artifacts/browser-suite')).resolve();out.mkdir(parents=True,exist_ok=True)
(root/'upgrade_review').mkdir(exist_ok=True)
entries=['browser','ui_terminal','acceptance_browser','brain_lab_browser','challenge_template_browser','discovery_browser','e_stage_browser','event_research_browser','phase4_browser','pool_browser','prediction_challenge_browser','protection_browser','replay_browser','research_browser','sizing_browser']
failures=[]
for name in entries:
    args=[sys.executable,'-X','utf8','-B',f'tests/{name}.py']
    if name=='browser':args += [str(out/'legacy-ui')]
    begin=datetime.datetime.now().astimezone().isoformat()
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','SMART_MONEY_RUNTIME':str(out/f'{name}-runtime'),'SMART_MONEY_UI_OUTPUT':str(out/f'{name}-ui')}
    job=Job();proc=None;code=None;error=None
    with (out/f'{name}.log').open('w',encoding='utf-8') as log:
        try:
            fixed={'browser':18784,'ui_terminal':18786}.get(name)
            if fixed:
                with socket.socket() as check:check.bind(('127.0.0.1',fixed))
            proc=job.launch(args,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
            code=proc.wait(timeout=100)
        except Exception as exc:error=repr(exc)
        finally:
            job.close()
            if proc:proc.wait(timeout=15)
    result=dict(name=name,command=subprocess.list2cmdline(args),start=begin,end=datetime.datetime.now().astimezone().isoformat(),exit=code,error=error)
    (out/f'{name}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(name,code,error,flush=True)
    if code!=0 or error:failures.append(name)
print(f'Browser suites: {len(entries)-len(failures)} passed, {len(failures)} failed',flush=True)
sys.exit(bool(failures))
