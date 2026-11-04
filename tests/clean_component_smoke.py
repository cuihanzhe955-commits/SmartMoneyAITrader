"""Optional component compatibility smoke in a separately installed interpreter."""
import argparse,json,os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.launcher import VERIFY_PACKAGES,REQUIREMENTS


def run(python):
    subprocess.run([python,"-c",VERIFY_PACKAGES,str(REQUIREMENTS)],cwd=ROOT,check=True)
    subprocess.run([python,"-m","pip","check"],check=True)
    with tempfile.TemporaryDirectory() as temp:
        with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        url="http://127.0.0.1:"+str(port)
        process=subprocess.Popen([python,"-X","utf8","-B","terminal_host.py","--no-browser","--port",str(port)],cwd=ROOT,env={**os.environ,"SMART_MONEY_RUNTIME":temp})
        def request(path,body=None):
            req=Request(url+path,data=None if body is None else json.dumps(body).encode(),headers={"Content-Type":"application/json"})
            with urlopen(req,timeout=5) as r:return json.load(r)
        try:
            for _ in range(100):
                try:
                    health=request("/api/health");break
                except OSError:time.sleep(.1)
            else:raise AssertionError("clean component server did not start")
            assert process.poll() is None, "isolated service must own its process"
            assert health["database"]
            created=request("/api/sessions",{"consent":True})
            before=request("/api/state")
            replay=request("/api/replay?session_id="+str(created["id"])+"&symbol=BTC&as_of=1722816000")
            assert len(replay["candles"])==240 and replay["read_only"]
            assert request("/api/state")["state"]==before["state"]
            return dict(dependency_verification=True,pip_check=True,server_started=True,graceful_shutdown=True,isolated_database=True,historical_replay_candles=240,account_access=False,orders_submitted=False)
        finally:
            try:request("/api/shutdown",{})
            finally:
                try:process.wait(15)
                except subprocess.TimeoutExpired:
                    process.terminate();process.wait(15)
                    raise RuntimeError("clean component graceful shutdown did not complete")


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--python",required=True);p.add_argument("--output",required=True);args=p.parse_args()
    result=run(args.python);Path(args.output).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");print(json.dumps(result))
