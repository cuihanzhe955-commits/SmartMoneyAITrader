"""Offline tests for the Windows source bootstrap; no trades, pip, or network calls."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

LAUNCHER = Path(__file__).resolve().parents[1] / 'scripts' / 'launcher.py'
spec = spec_from_file_location('smat_launcher_test_subject', LAUNCHER)
launcher = module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_port_reports_existing_matching_instance_without_starting():
    with patch.object(launcher, 'status', return_value='ours'), \
         patch.object(launcher, 'ensure_venv') as venv, \
         patch.object(launcher, 'webbrowser') as browser:
        assert launcher.main([]) == 0
        venv.assert_not_called()
        browser.open.assert_called_once_with('http://127.0.0.1:8785')


def test_port_conflict_does_not_install_or_launch():
    with patch.object(launcher, 'status', return_value='occupied'), \
         patch.object(launcher, 'ensure_venv') as venv, \
         patch.object(launcher, 'subprocess') as process:
        assert launcher.main([]) == 3
        venv.assert_not_called()
        process.run.assert_not_called()


def test_install_only_does_not_probe_port_or_start_service():
    with patch.object(launcher, 'status') as status, \
         patch.object(launcher, 'ensure_venv', return_value=True), \
         patch.object(launcher, 'ensure_dependencies', return_value=True), \
         patch.object(launcher, 'subprocess') as proc:
        assert launcher.main(['--install-only']) == 0
        status.assert_not_called()
        proc.run.assert_not_called()


def test_no_browser_forwards_custom_port_to_original_host():
    with patch.object(launcher, 'status', return_value='free'), \
         patch.object(launcher, 'ensure_venv', return_value=True), \
         patch.object(launcher, 'ensure_dependencies', return_value=True), \
         patch.object(launcher, 'subprocess') as process, \
         patch.object(launcher, 'webbrowser') as browser:
        process.run.return_value = SimpleNamespace(returncode=0)
        assert launcher.main(['--no-browser', '--port', '18788']) == 0
        args = process.run.call_args.args[0]
        assert args[:2] == [str(launcher.VENV_PY), '-B']
        assert args[2].endswith('terminal_host.py')
        assert args[-3:] == ['--no-browser', '--port', '18788']
        browser.open.assert_not_called()


def test_no_venv_means_no_launch():
    with patch.object(launcher, 'status', return_value='free'), \
         patch.object(launcher, 'ensure_venv', return_value=False), \
         patch.object(launcher, 'ensure_dependencies') as dependencies, \
         patch.object(launcher, 'subprocess') as process:
        assert launcher.main([]) == 4
        dependencies.assert_not_called()
        process.run.assert_not_called()


def test_dependency_check_uses_pinned_requirements_and_imports():
    assert 'version(package.strip()) != expected.strip()' in launcher.VERIFY_PACKAGES
    assert '"win32crypt"' in launcher.VERIFY_PACKAGES
    with patch.object(launcher, 'subprocess') as process:
        process.run.return_value = SimpleNamespace(returncode=0)
        assert launcher.dependencies_ok()
        assert str(launcher.REQUIREMENTS) in process.run.call_args.args[0]


def test_incomplete_existing_venv_is_not_deleted(tmp_path):
    venv = tmp_path / '.venv'
    venv.mkdir()
    sentinel = venv / 'keep-me.txt'
    sentinel.write_text('important')
    with patch.object(launcher, 'VENV', venv), \
         patch.object(launcher, 'VENV_PY', venv / 'Scripts' / 'python.exe'), \
         patch.object(launcher, 'subprocess') as process:
        assert not launcher.ensure_venv()
        assert sentinel.read_text() == 'important'
        process.run.assert_not_called()
