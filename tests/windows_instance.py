"""Owned Windows test process tree; no port/PID based process discovery."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from urllib.request import Request, urlopen


class Job:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                        ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise ctypes.WinError(error)

    def launch(self, command, **kwargs):
        # Suspend BEFORE any launcher code runs, so no descendant can escape ownership.
        p = subprocess.Popen(command, creationflags=0x4, **kwargs)
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, int(p._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            resume = ctypes.WinDLL('ntdll').NtResumeProcess
            resume.argtypes = [wintypes.HANDLE]
            resume.restype = ctypes.c_long
            if resume(int(p._handle)) != 0:
                raise OSError('could not resume owned process')
            return p
        except BaseException:
            p.kill()
            p.wait(timeout=10)
            raise

    def close(self):
        if self.handle:
            if not self.kernel.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class Instance:
    def __init__(self, root, runtime, timeout=45, port=0, entry='start.bat'):
        self.root = Path(root)
        self.runtime = Path(runtime)
        self.timeout = timeout
        self.port = port
        self.entry = entry
        self.identity = uuid.uuid4().hex
        self.ready = self.runtime / (self.identity + '.ready.json')
        self.url = None
        self.process = None
        self.job = None

    def request(self, path, body=None):
        with urlopen(Request(self.url + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type': 'application/json', 'X-Smart-Money-Instance': self.identity}), timeout=15) as response:
            return json.load(response)

    def wait_ready(self):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f'launcher exited: {self.process.returncode}')
            try:
                record = json.loads(self.ready.read_text(encoding='utf-8'))
                if record['instance_id'] != self.identity:
                    raise RuntimeError('wrong rendezvous instance')
                self.url = record['url']
                health = self.request('/api/health')
                if (health.get('instance_id') != self.identity or health.get('pid') != record['pid']
                        or health.get('product') != 'Smart Money AI Trader'):
                    raise RuntimeError('wrong health instance')
                return
            except (OSError, ValueError):
                time.sleep(.1)
        raise TimeoutError('startup timed out')

    def start(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.job = Job()
        try:
            self.process = self.job.launch(['cmd', '/c', self.entry, '--no-browser', '--port', str(self.port),
                    '--instance-id', self.identity, '--ready-file', str(self.ready)], cwd=self.root,
                    env={**os.environ, 'SMART_MONEY_RUNTIME': str(self.runtime), 'SMART_MONEY_NO_PAUSE': '1'})
            self.wait_ready()
            return self
        except BaseException:
            self.close()
            raise

    def crash(self):
        if self.job:
            self.job.close()
            self.job = None
        if self.process:
            self.process.wait(timeout=15)

    def close(self):
        # Job membership is the cleanup authority even if bootstrap already exited.
        try:
            if self.url and self.process and self.process.poll() is None:
                try:
                    health = self.request('/api/health')
                    if health.get('instance_id') == self.identity:
                        self.request(f'/api/instances/{self.identity}/shutdown', {})
                        self.process.wait(timeout=15)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
        finally:
            self.crash()
            self.ready.unlink(missing_ok=True)
