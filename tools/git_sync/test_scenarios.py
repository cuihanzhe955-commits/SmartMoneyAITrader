import os, subprocess, tempfile, importlib.util, contextlib, io, pathlib, re, shutil
src=str(pathlib.Path(__file__).resolve().parent / 'smartmoney_sync.py')
spec=importlib.util.spec_from_file_location('smartmoney_sync_zh',src); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
class AcceptLocal:
    def fullmatch(self,x):return True
mod.EXPECTED_REPO=AcceptLocal()

def cmd(cwd,*args):
    p=subprocess.run(args,cwd=cwd,text=True,capture_output=True,timeout=30)
    if p.returncode: raise RuntimeError(f'git command failed {args}: {p.stderr} {p.stdout}')
    return p.stdout.strip()

def prepare(base):
    base=pathlib.Path(base); remote=base/'remote.git'; local=base/'local'; other=base/'other'
    cmd(base,'git','init','-b','main','--bare',str(remote))
    cmd(base,'git','clone',str(remote),str(local))
    for path in (local,):
        cmd(path,'git','config','user.email','test@localhost');cmd(path,'git','config','user.name','Test')
    (local/'tests').mkdir()
    (local/'tests'/'run_offline.py').write_text('print("离线测试通过")\n',encoding='utf8')
    (local/'.gitignore').write_text('__pycache__/\n.pytest_cache/\n',encoding='utf8')
    (local/'base.txt').write_text('original\n',encoding='utf8')
    cmd(local,'git','add','tests/run_offline.py','.gitignore','base.txt');cmd(local,'git','commit','-m','baseline');cmd(local,'git','push','origin','main')
    cmd(base,'git','clone',str(remote),str(other));cmd(other,'git','config','user.email','test@localhost');cmd(other,'git','config','user.name','Test')
    return local,other

def commit(path,name,data='updated\n',delete=False):
    f=path/name
    if delete:f.unlink()
    else:f.parent.mkdir(parents=True,exist_ok=True);f.write_text(data,encoding='utf8')
    cmd(path,'git','add','-A');cmd(path,'git','commit','-m',f'update {name}')

def run_case(name,loc=None,rem=None,mode='sync',dirty=False, expect=0):
    with tempfile.TemporaryDirectory(prefix='smart_zh_case_') as temp:
        local,other=prepare(temp)
        if loc:commit(local,*loc)
        if rem:commit(other,*rem);cmd(other,'git','push','origin','main')
        if dirty:(local/'base.txt').write_text('dirty\n',encoding='utf8')
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):ret=mod.go(['--project',str(local),'--mode',mode])
        report=list((local.parent/'SmartMoneyAITrader_SYNC_BACKUPS').glob('*/同步报告.txt'))
        assert len(report)==1,(name,report)
        txt=report[0].read_text('utf-8')
        assert '中文安全同步报告' in txt and '本轮备份目录' in txt,(name,txt)
        assert (report[0].parent/'git_history.bundle').exists(),name
        assert (report[0].parent/'source_snapshot.zip').exists(),name
        assert ret==expect,(name,ret,txt,buf.getvalue())
        if mode=='audit': assert '仅检查模式' in txt,(name,txt)
        if expect:assert '[安全停止]' in txt,(name,txt)
        if not expect and mode=='sync':assert '[成功]' in txt or '[完成]' in txt,(name,txt)
        if loc and rem and loc[0]!=rem[0] and expect==0 and mode=='sync':
            assert (local/loc[0]).exists() and (local/rem[0]).exists(),name
        print('PASS',name,'exit=',ret,'summary=',[x for x in txt.splitlines() if '[成功]' in x or '[安全停止]' in x or '[完成]' in x][-1])

run_case('already-same')
run_case('local-ahead',loc=('local.txt','local\n'))
run_case('remote-ahead',rem=('remote.txt','remote\n'))
run_case('disjoint-merge',loc=('local.txt','local\n'),rem=('remote.txt','remote\n'))
run_case('same-path-conflict',loc=('base.txt','local\n'),rem=('base.txt','remote\n'),expect=2)
run_case('dirty-working-tree',dirty=True,expect=2)
run_case('remote-delete',rem=('base.txt','',True),expect=2)
run_case('audit-disjoint',loc=('local.txt','local\n'),rem=('remote.txt','remote\n'),mode='audit')
run_case('secrets-commit',loc=('.env','SECRET=somekey\n'),expect=2)
print('ALL TEST CASES PASS')