"""Build-job smoke: generated Compose startup, owner claim, publication and restart."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pretty_notebook._internal.deployment import DeploySpec, write_bundle


def run(*arguments):
    return subprocess.run(arguments, check=True, text=True, capture_output=True, timeout=90).stdout.strip()


def smoke(revision):
    with tempfile.TemporaryDirectory(prefix='pnbp-container-smoke-') as temporary:
        root = Path(temporary)
        state = root / 'state'
        state.mkdir(mode=0o700)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        environment = root / 'environment'
        environment.write_text(f'''PNBP_DATA_DIR=/var/lib/pretty-notebook
PNBP_DATABASE_URL=sqlite:///var/lib/pretty-notebook/db.sqlite3
PNBP_ALLOWED_HOSTS=127.0.0.1
PNBP_ASSET_MODE=local
PNBP_URL_PREFIX=
PNBP_PORT={port}
PNBP_WORKERS=4
JWT_ALGO=HS256
JWT_SECRET=synthetic-container-jwt-secret-32-bytes
PNBP_BOOTSTRAP_TOKEN=synthetic-container-bootstrap-32-bytes
''')
        environment.chmod(0o600)
        spec = DeploySpec(revision, 'notes.example.com', checkout=Path.cwd(), data_dir=state,
                          env_file=environment, backup_dir=root / 'backups', port=port,
                          service='pnbp-smoke-' + str(os.getpid()))
        output = root / 'bundle'
        write_bundle(spec, output, profile='container')
        image = 'pretty-notebook:' + revision
        compose = ['docker', 'compose', '--file', str(output / 'compose.json')]
        # Ownership changes are confined to this disposable synthetic fixture.
        def ownership(uid, gid):
            run('docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '--entrypoint', 'python',
                '--mount', f'type=bind,source={state},target=/fixture', image,
                '-c', f'import os; [(os.chown(p, {uid}, {gid})) for p in ["/fixture", *[os.path.join(r,n) for r,ds,fs in os.walk("/fixture") for n in ds+fs]]]')
        def request(path, *, data=None, headers=None, method=None):
            with urlopen(Request(f'http://127.0.0.1:{port}' + path, data=data, headers=headers or {}, method=method), timeout=5) as response:
                return response.read()
        def healthy():
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    if json.loads(request('/healthz')) == {'status': 'ok'}:
                        return
                except (URLError, ValueError):
                    pass
                time.sleep(0.2)
            raise AssertionError('Container never became healthy.')
        ownership(10001, 10001)
        try:
            run(*compose, 'config', '--quiet')
            run(*compose, 'up', '--detach', '--no-build', '--pull', 'never')
            healthy()
            try:
                request('/healthz', headers={'Host': 'untrusted.example'})
                raise AssertionError('Untrusted host accepted.')
            except HTTPError as error:
                assert error.code == 400
            request('/api/users', data=json.dumps({'username': 'owner', 'password_hash': 'synthetic-password-123'}).encode(),
                    headers={'Content-Type': 'application/json', 'X-PNBP-Bootstrap-Token': 'synthetic-container-bootstrap-32-bytes'})
            token = json.loads(request('/api/token', data=urlencode({'username': 'owner', 'password': 'synthetic-password-123'}).encode(),
                                       headers={'Content-Type': 'application/x-www-form-urlencoded'}))['access_token']
            headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
            request('/api/publishment', data=json.dumps({'name': 'persistent', 'content': '<p>Container survives</p>'}).encode(), headers=headers)
            for _ in range(2):
                run(*compose, 'up', '--detach', '--no-build', '--pull', 'never')
                run(*compose, 'restart')
                healthy()
                assert b'Container survives' in request('/persistent')
                assert json.loads(request('/api/users/me', headers={'Authorization': 'Bearer ' + token}))['username'] == 'owner'
            print('Container smoke passed: generated Compose, four-worker startup, host filtering, owner claim, publication, idempotent rerun and two restarts.')
        except Exception:
            print(run('docker', 'logs', '--tail', '100', spec.service), file=sys.stderr)
            raise
        finally:
            run(*compose, 'down', '--timeout', '10')
            ownership(os.getuid(), os.getgid())


if __name__ == '__main__':
    smoke(sys.argv[1])
