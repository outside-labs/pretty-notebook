"""Exercise real processes, shared state, bootstrap races and stale writes."""

import hashlib
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
import requests
from api import schema

WEB_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def server(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    # Test-only middleware identifies the worker that served each response.
    (tmp_path / 'worker_fixture.py').write_text('''from main import api
import os
@api.middleware("http")
async def identify(request, call_next):
    response = await call_next(request)
    response.headers["X-Test-Worker"] = str(os.getpid())
    return response
''')
    state = tmp_path / 'state'
    environment = {**os.environ, 'JWT_SECRET': 'worker-test-jwt-secret-32-bytes-xxxx',
                   'JWT_ALGO': 'HS256', 'PNBP_DATA_DIR': str(state),
                   'PNBP_DATABASE_URL': f'sqlite://{state / "db.sqlite3"}',
                   'PNBP_ALLOWED_HOSTS': '127.0.0.1', 'PNBP_ASSET_MODE': 'local',
                   'PNBP_URL_PREFIX': '', 'PNBP_BOOTSTRAP_TOKEN': 'worker-test-bootstrap-token-32-bytes',
                   'PYTHONPATH': os.pathsep.join((str(tmp_path), str(WEB_ROOT)))}
    with (tmp_path / 'server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'gunicorn', 'worker_fixture:api',
                                    '--no-control-socket', '--control-socket', str(tmp_path / 'administration.ctl'),
                                    '--workers', '4', '--worker-class', 'uvicorn_worker.UvicornWorker',
                                    '--bind', f'127.0.0.1:{port}'], cwd=WEB_ROOT,
                                   env=environment, stdout=log, stderr=log, start_new_session=True)
        base = f'http://127.0.0.1:{port}'
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None: break
                try:
                    if requests.get(base + '/healthz', timeout=1).status_code == 200:
                        assert not (tmp_path / "administration.ctl").exists()
                        yield base
                        return
                except requests.RequestException:
                    pass
                time.sleep(0.05)
            pytest.fail('Four-worker startup failed: ' + (tmp_path / 'server.log').read_text()[-6000:])
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


def publication(body):
    digest = hashlib.sha256(body.encode()).hexdigest()
    return {'name': 'shared', 'content': body, 'source_hash': digest,
            'rendered_hash': digest, 'renderer_fingerprint': 'f' * 64}


def all_workers_read(base, expected):
    seen = set()
    for _ in range(20):
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: requests.get(base + '/shared', timeout=5), range(8)))
        for response in responses:
            assert response.status_code == 200 and expected in response.text
            seen.add(response.headers['X-Test-Worker'])
        if len(seen) == 4: return
    assert len(seen) == 4, 'Requests did not exercise all four workers'


@pytest.mark.skipif(os.name != 'posix', reason='Supported web deployment is Linux/POSIX')
@pytest.mark.parametrize('legacy', [False, True])
def test_four_workers_coordinate_startup_claims_and_checked_writes(tmp_path, legacy):
    state = tmp_path / 'state'
    state.mkdir()
    database = state / 'db.sqlite3'
    if legacy:
        with closing(sqlite3.connect(database)) as connection:
            for statement in schema.BASE_SCHEMA: connection.execute(statement)
            connection.commit()
        (state / 'pages').mkdir()
        (state / 'pages/legacy.html').write_text('<p>Legacy survives</p>')
    with server(tmp_path) as base:
        password = 'worker-test-password-123'
        def claim(index):
            return requests.post(base + '/api/users', json={'username': f'owner-{index}', 'password_hash': password},
                                 headers={'X-PNBP-Bootstrap-Token': 'worker-test-bootstrap-token-32-bytes'}, timeout=10)
        with ThreadPoolExecutor(max_workers=8) as pool: claims = list(pool.map(claim, range(8)))
        assert sorted(response.status_code for response in claims) == [200] + [401] * 7
        owner = next(response.json()['username'] for response in claims if response.status_code == 200)
        login = requests.post(base + '/api/token', data={'username': owner, 'password': password}, timeout=5)
        assert login.status_code == 200
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        initial = requests.put(base + '/api/publishing/publication', json=publication('<p>First</p>'),
                               headers={**headers, 'If-None-Match': '*'}, timeout=5)
        assert initial.status_code == 201, initial.text
        etag = initial.headers['ETag']
        def write(index):
            return requests.put(base + '/api/publishing/publication', json=publication(f'<p>Winner {index}</p>'),
                                headers={**headers, 'If-Match': etag}, timeout=10)
        with ThreadPoolExecutor(max_workers=8) as pool: writes = list(pool.map(write, range(8)))
        assert sorted(response.status_code for response in writes) == [200] + [412] * 7
        winner = next(index for index, response in enumerate(writes) if response.status_code == 200)
        all_workers_read(base, f'Winner {winner}')
        if legacy: assert 'Legacy survives' in requests.get(base + '/legacy', timeout=5).text
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute('SELECT COUNT(*) FROM pnbp_schema_migrations').fetchone()[0] == schema.CURRENT_VERSION
            assert connection.execute("SELECT current_revision FROM pnbp_notes WHERE canonical_route='/shared'").fetchone()[0] == 2
            assert connection.execute('SELECT COUNT(*) FROM user').fetchone()[0] == 1
        migrations = sorted((state / 'migration-backups').glob('*')) if legacy else []
        assert len(migrations) == (1 if legacy else 0)
    with server(tmp_path) as base:
        all_workers_read(base, f'Winner {winner}')
        if legacy:
            assert sorted((state / 'migration-backups').glob('*')) == migrations
