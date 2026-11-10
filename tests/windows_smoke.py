"""Actual Windows entries, interrupted isolated replay, owned-tree cleanup."""
import tempfile
import time
from pathlib import Path
from windows_instance import Instance
ROOT = Path(__file__).resolve().parents[1]


def run():
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts.launcher import dependencies_ok
    if not dependencies_ok():
        raise RuntimeError("Precondition: run start.bat --install-only before Windows smoke")
    with tempfile.TemporaryDirectory(prefix='smat-windows-') as tmp:
        first = Instance(ROOT, tmp)
        second = None
        try:
            first.start()
            first.request('/api/sessions', {'consent': True, 'speed': 3600, 'settlement': 'close', 'capital': 1000, 'profile': 'normal', 'loss_limit': 90, 'breaker': 50})
            first.request('/api/command', {'cmd': 'start', 'id': 1})
            time.sleep(4)
            first.crash()
            second = Instance(ROOT, tmp, entry='start.cmd').start()
            until = time.monotonic() + 100
            d = {}
            while time.monotonic() < until:
                d = second.request('/api/state')
                if d.get('report'):
                    break
                time.sleep(1)
            assert d['state']['lifecycle_status'] == 'COMPLETED', d
            assert d['report']['fills'] == 272 and abs(d['report']['nav'] - 943.8943549007662) < 1e-7, d['report']
            # Verify the legacy stop.bat entry with a required instance identity.
            import subprocess
            result = subprocess.run(['cmd', '/c', 'stop.bat', '--port', second.url.rsplit(':', 1)[1], '--instance-id', second.identity], cwd=ROOT, timeout=20)
            assert result.returncode == 0
            second.process.wait(timeout=15)
            assert second.process.returncode == 0
            print('PASS Windows start.bat/start.cmd/stop.bat, isolated restart, 272 fills, exact NAV, owned cleanup.')
        finally:
            if second:
                second.close()
            first.close()
    assert not Path(tmp).exists()


if __name__ == '__main__':
    run()
