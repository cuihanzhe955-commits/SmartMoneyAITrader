"""Exercise the actual .bat launcher, an interrupted replay, report and safe shutdown."""
import os
import time
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen,Request
ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:18788'
def get(path,body=None):
    return json.load(urlopen(Request(URL+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=15))
def run():
    with tempfile.TemporaryDirectory() as tmp:
        env=dict(os.environ,SMART_MONEY_RUNTIME=tmp)
        def boot():
            p=subprocess.Popen(['cmd','/c','start.bat','--no-browser','--port','18788'],cwd=ROOT,env=env)
            for _ in range(100):
                try:get('/api/health');return p
                except OSError:time.sleep(.15)
            raise AssertionError('startup timed out')
        p=boot()
        try:
            get('/api/sessions',{'consent':True,'speed':3600,'settlement':'close','capital':1000,'profile':'normal','loss_limit':90,'breaker':50})
            get('/api/command',{'cmd':'start','id':1});time.sleep(4)
            # Kill only the temporary Windows test process tree.
            subprocess.run(['taskkill','/t','/f','/pid',str(p.pid)],check=True,stdout=subprocess.DEVNULL);p.wait()
            p=boot();until=time.time()+100
            while time.time()<until:
                d=get('/api/state')
                if d.get('report'):break
                time.sleep(1)
            assert d['state']['lifecycle_status']=='COMPLETED'
            assert d['report']['fills']==272 and abs(d['report']['nav']-943.8943549007662)<1e-7,d['report']
            print('PASS Windows launch, interrupted full replay, identical 272 fills and NAV.')
        finally:
            subprocess.run(['cmd','/c','stop.bat','--port','18788'],cwd=ROOT,check=True)
            p.wait(timeout=12)
if __name__=='__main__':run()

