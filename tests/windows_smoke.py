"""Actual Windows entries, interrupted isolated replay, owned-tree cleanup."""
from contextlib import closing
import tempfile
import time
from pathlib import Path
from windows_instance import Instance
ROOT = Path(__file__).resolve().parents[1]


def run(interrupt=True):
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts.launcher import dependencies_ok
    if not dependencies_ok():
        raise RuntimeError("Precondition: run start.bat --install-only before Windows smoke")
    with tempfile.TemporaryDirectory(prefix='smat-windows-') as tmp:
        first = Instance(ROOT, tmp)
        second = None
        try:
            launched=time.perf_counter()
            first.start()
            startup=time.perf_counter()-launched
            first.request('/api/sessions', {'consent': True, 'speed': 3600, 'settlement': 'close', 'capital': 1000, 'profile': 'normal', 'loss_limit': 90, 'breaker': 50})
            first.request('/api/command', {'cmd': 'start', 'id': 1})
            if interrupt:
                time.sleep(4)
                first.crash()
                launched=time.perf_counter()
                second = Instance(ROOT, tmp, entry='start.cmd').start()
                startup=time.perf_counter()-launched
            else:
                second = first
            until = time.monotonic() + 100
            d = {}
            while time.monotonic() < until:
                d = second.request('/api/state')
                if d.get('report'):
                    break
                time.sleep(1)
            assert d['state']['lifecycle_status'] == 'COMPLETED', d
            assert d['report']['fills'] == 272 and abs(d['report']['nav'] - 943.8943549007662) < 1e-7, d['report']
            assert d['report']['end']-d['report']['start']==86400
            import sqlite3,json
            with closing(sqlite3.connect(Path(tmp)/'terminal.db')) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                times=[r[0] for r in db.execute('SELECT t FROM market_snapshots ORDER BY t')]
                assert times==list(range(d['report']['start'],d['report']['end']+1,60))
                ledger=[(t,symbol,kind,json.loads(data)) for t,symbol,kind,data in db.execute('SELECT t,symbol,kind,data FROM fills ORDER BY id')]
            print('PERF',dict(interrupt=interrupt,startup_seconds=startup,recovery_seconds=time.monotonic()-(until-100)),flush=True)
            # Verify the legacy stop.bat entry with a required instance identity.
            import subprocess
            result = subprocess.run(['cmd', '/c', 'stop.bat', '--port', second.url.rsplit(':', 1)[1], '--instance-id', second.identity], cwd=ROOT, timeout=20)
            assert result.returncode == 0
            second.process.wait(timeout=15)
            assert second.process.returncode == 0
            trace=Path(tmp)/'acceptance-performance.jsonl'
            if trace.exists():
                import os,uuid
                target=Path(os.environ.get('SMART_MONEY_PERF_OUTPUT', ROOT/'artifacts/replay-traces'))
                target.mkdir(parents=True,exist_ok=True)
                (target/(uuid.uuid4().hex+'.jsonl')).write_bytes(trace.read_bytes())
            print('PASS Windows start.bat/start.cmd/stop.bat, isolated restart, 272 fills, exact NAV, owned cleanup.')
        finally:
            if second:
                second.close()
            first.close()
    assert not Path(tmp).exists()
    return ledger


if __name__ == '__main__':
    baseline=run(False)
    for _ in range(3):
        assert run()==baseline
