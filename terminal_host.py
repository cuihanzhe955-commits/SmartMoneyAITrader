import argparse
import json
import os
from pathlib import Path
import socket
import threading
import uuid
import webbrowser
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uvicorn
from terminal.api import app


def bind_listener(port):
    """Retain OS allocation through uvicorn shutdown, including port zero."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(('127.0.0.1', port))
        sock.listen(128)
        sock.setblocking(False)
        return sock
    except BaseException:
        sock.close()
        raise


def health_matches(url, instance_id=None):
    try:
        with urlopen(url + '/api/health', timeout=0.6) as response:
            data = json.load(response)
        return (data.get('product') == 'Smart Money AI Trader'
                and (instance_id is None or data.get('instance_id') == instance_id))
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', default=8785, type=int)
    parser.add_argument('--instance-id')
    parser.add_argument('--ready-file')
    a = parser.parse_args()
    if not 0 <= a.port <= 65535 or (a.stop and not a.port):
        parser.error('invalid port')
    url = f'http://127.0.0.1:{a.port}'
    if a.stop:
        if a.instance_id and not health_matches(url, a.instance_id):
            raise SystemExit('服务实例不匹配；未发送停止请求。')
        headers = {'Content-Type': 'application/json'}
        if a.instance_id:
            headers['X-Smart-Money-Instance'] = a.instance_id
        endpoint = f'/api/instances/{a.instance_id}/shutdown' if a.instance_id else '/api/shutdown'
        try:
            with urlopen(Request(url + endpoint, data=b'{}', headers=headers), timeout=10) as response:
                print(response.read().decode())
        except HTTPError as e:
            print(e.read().decode())
            raise SystemExit(1)
        except OSError:
            print('服务未运行。')
        return
    # Preserve normal desktop attach; isolated launches never attach by product name.
    if not a.instance_id and a.port and health_matches(url):
        if not a.no_browser:
            webbrowser.open(url)
        return
    instance_id = a.instance_id or uuid.uuid4().hex
    app.state.instance_id = instance_id
    app.state.isolated_instance = bool(a.instance_id)
    ready_file = Path(a.ready_file) if a.ready_file else None
    if ready_file and ready_file.exists():
        raise SystemExit('ready file already exists')
    with bind_listener(a.port) as listener:
        url = f'http://127.0.0.1:{listener.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        app.state.request_shutdown = lambda: setattr(server, 'should_exit', True)
        finished = threading.Event()

        def announce():
            while not finished.wait(0.1):
                if server.started and health_matches(url, instance_id):
                    try:
                        if ready_file:
                            with ready_file.open('x', encoding='utf-8') as stream:
                                json.dump({'url': url, 'instance_id': instance_id, 'pid': os.getpid()}, stream)
                        print('Smart Money AI Trader ' + url, flush=True)
                        if not a.no_browser:
                            webbrowser.open(url)
                    except OSError:
                        server.should_exit = True
                    return

        worker = threading.Thread(target=announce, daemon=True)
        worker.start()
        try:
            server.run(sockets=[listener])
        finally:
            finished.set()
            worker.join(timeout=2)


if __name__ == '__main__':
    main()
