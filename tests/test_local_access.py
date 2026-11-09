from fastapi.testclient import TestClient
import pytest
from terminal.api import create_app


@pytest.mark.parametrize('peer,host,headers', [
    ('192.0.2.1', '127.0.0.1', {}),
    ('127.0.0.1', 'external.invalid', {}),
    ('127.0.0.1', 'localhost', {'origin': 'https://external.invalid'}),
    ('127.0.0.1', 'localhost', {'sec-fetch-site': 'cross-site'}),
    ('127.0.0.1', 'localhost', {'content-type': 'text/plain'}),
    ('127.0.0.1', 'localhost', {'content-type': 'application/json-invalid'}),
])
def test_foreign_control_requests_rejected_before_route(tmp_path, peer, host, headers):
    with TestClient(create_app(tmp_path), client=(peer, 1234)) as api:
        result = api.post('/api/research/challenges/command', json={}, headers={'host':host, **headers})
        assert result.status_code == 403
