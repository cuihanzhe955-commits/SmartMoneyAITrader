"""Instance safety contract. All filesystem state is pytest temporary state."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from terminal.api import create_app
from terminal_host import bind_listener, health_matches

spec = importlib.util.spec_from_file_location('windows_instance', Path(__file__).with_name('windows_instance.py'))
wi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wi)


def test_bound_zero_port_cannot_be_stolen():
    with bind_listener(0) as owned:
        port = owned.getsockname()[1]
        with pytest.raises(OSError):
            bind_listener(port)
    with bind_listener(port):
        pass


def test_occupied_unrelated_listener_is_untouched():
    with socket.socket() as other:
        other.bind(('127.0.0.1', 0))
        other.listen()
        with pytest.raises(OSError):
            bind_listener(other.getsockname()[1])
        assert other.fileno() != -1


def test_health_checks_identity_not_only_product():
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps({'product': 'Smart Money AI Trader', 'instance_id': 'other'})
    with patch('terminal_host.urlopen', return_value=response):
        assert not health_matches('http://127.0.0.1:1', 'mine')
        assert health_matches('http://127.0.0.1:1')


def test_mutations_reject_missing_or_wrong_instance(tmp_path):
    app = create_app(tmp_path)
    app.state.instance_id = 'mine'
    app.state.isolated_instance = True
    app.state.request_shutdown = Mock()
    with TestClient(app) as client:
        assert client.get('/api/health').json()['instance_id'] == 'mine'
        for headers in ({}, {'X-Smart-Money-Instance': 'other'}):
            assert client.post('/api/shutdown', json={}, headers=headers).status_code == 409
        app.state.request_shutdown.assert_not_called()
        assert client.post('/api/shutdown', json={}, headers={'X-Smart-Money-Instance': 'mine'}).status_code == 200
        app.state.request_shutdown.assert_called_once()


@pytest.mark.parametrize('cause', ['spawn', 'timeout', 'wrong_health', 'early_exit'])
def test_failed_boot_always_closes_owned_job(tmp_path, cause):
    instance = wi.Instance(tmp_path, tmp_path, timeout=0)
    job = Mock()
    job.launch.return_value = Mock()
    if cause == 'spawn':
        job.launch.side_effect = OSError('synthetic spawn failure')
    failure = TimeoutError() if cause == 'timeout' else RuntimeError(cause)
    with patch.object(wi, 'Job', return_value=job), patch.object(instance, 'wait_ready', side_effect=failure):
        with pytest.raises((OSError, RuntimeError)):
            instance.start()
    job.close.assert_called_once()


def test_wrong_health_aborts_before_commands(tmp_path):
    instance = wi.Instance(tmp_path, tmp_path)
    instance.ready.write_text(json.dumps({'instance_id': instance.identity, 'pid': 123, 'url': 'http://127.0.0.1:1'}))
    instance.process = Mock()
    instance.process.poll.return_value = None
    with patch.object(instance, 'request', return_value={'product': 'Smart Money AI Trader', 'instance_id': 'other', 'pid': 123}) as req:
        with pytest.raises(RuntimeError, match='wrong health'):
            instance.wait_ready()
        req.assert_called_once_with('/api/health')


def test_no_shutdown_sent_to_replacement_instance(tmp_path):
    instance = wi.Instance(tmp_path, tmp_path)
    instance.url = 'http://127.0.0.1:1'
    instance.process = Mock()
    instance.process.poll.return_value = None
    instance.job = Mock()
    job = instance.job
    with patch.object(instance, 'request', return_value={'instance_id': 'other'}) as req:
        instance.close()
        req.assert_called_once_with('/api/health')
    job.close.assert_called_once()


def test_actual_job_cleanup_does_not_kill_unrelated_process():
    other = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
    job = wi.Job()
    owned = None
    try:
        owned = job.launch([sys.executable, '-c', 'import time;time.sleep(60)'])
        job.close()
        owned.wait(timeout=10)
        assert other.poll() is None
    finally:
        job.close()
        other.terminate()
        other.wait(timeout=10)


def test_actual_timeout_cleans_spawned_job(tmp_path):
    instance = wi.Instance(tmp_path, tmp_path, timeout=0)
    job = wi.Job()
    proc = job.launch([sys.executable, '-c', 'import time;time.sleep(60)'])
    instance.job, instance.process = job, proc
    try:
        with pytest.raises(TimeoutError):
            instance.wait_ready()
    finally:
        instance.close()
    assert proc.poll() is not None
    assert not instance.ready.exists()

def test_identity_scoped_stop_rejects_other_id(tmp_path):
    app = create_app(tmp_path)
    app.state.instance_id = 'mine'
    app.state.request_shutdown = Mock()
    with TestClient(app) as client:
        assert client.post('/api/instances/other/shutdown', json={}).status_code == 409
        app.state.request_shutdown.assert_not_called()
        assert client.post('/api/instances/mine/shutdown', json={}).status_code == 200
        app.state.request_shutdown.assert_called_once()


def test_actual_two_hosts_and_wrong_stop(tmp_path):
    """Real listeners + temporary DBs; scoped stop cannot affect a second instance."""
    root = Path(__file__).resolve().parents[1]
    instances = []
    try:
        for _ in range(2):
            instance = wi.Instance(root, tmp_path / str(len(instances)))
            instance.runtime.mkdir()
            instance.job = wi.Job()
            instances.append(instance)
            instance.process = instance.job.launch([sys.executable, '-X', 'utf8', '-B', str(root / 'terminal_host.py'),
                    '--no-browser', '--port', '0', '--instance-id', instance.identity, '--ready-file', str(instance.ready)],
                    cwd=root, env={**wi.os.environ, 'SMART_MONEY_RUNTIME': str(instance.runtime)})
            instance.wait_ready()
        a, b = instances
        assert a.url != b.url
        result = subprocess.run([sys.executable, '-B', 'terminal_host.py', '--stop', '--port', b.url.rsplit(':', 1)[1], '--instance-id', a.identity], cwd=root, capture_output=True, timeout=15)
        assert result.returncode != 0
        assert b.request('/api/health')['instance_id'] == b.identity
        a.close()
        assert a.process.poll() is not None
        assert b.process.poll() is None
        assert b.request('/api/health')['database']
    finally:
        for instance in instances:
            instance.close()


def test_child_surviving_launcher_exit_is_owned(tmp_path):
    import time
    heartbeat = tmp_path / 'heartbeat'
    child = f"import time;from pathlib import Path;p=Path({str(heartbeat)!r});\nwhile True:p.write_text(str(time.time()));time.sleep(.05)"
    parent = f'import subprocess,sys;subprocess.Popen([sys.executable,"-c",{child!r}])'
    job = wi.Job()
    try:
        proc = job.launch([sys.executable, '-c', parent])
        proc.wait(timeout=10)
        deadline = time.monotonic() + 10
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert heartbeat.exists()
        job.close()
        time.sleep(.2)
        saved = heartbeat.read_text()
        time.sleep(.2)
        assert heartbeat.read_text() == saved
    finally:
        job.close()
