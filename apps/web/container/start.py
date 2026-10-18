"""Validate the single-host container contract, then replace PID 1 with Gunicorn."""

import os
from pathlib import Path
import sys


def command(environment, *, uid, state):
    if uid == 0:
        raise ValueError('Run the container as the dedicated non-root user.')
    if (state.is_symlink() or not state.is_dir() or state.stat().st_uid != uid
            or state.stat().st_mode & 0o077):
        raise ValueError('State must be a private directory owned by the container user.')
    expected = {'PNBP_DATA_DIR': '/var/lib/pretty-notebook',
                'PNBP_DATABASE_URL': 'sqlite:///var/lib/pretty-notebook/db.sqlite3',
                'PNBP_ASSET_MODE': 'local', 'JWT_ALGO': 'HS256'}
    for key, value in expected.items():
        if environment.get(key, value) != value:
            raise ValueError(f'{key} does not match the container profile.')
    for key in ('JWT_SECRET', 'PNBP_BOOTSTRAP_TOKEN'):
        value = environment.get(key, '')
        if (key == 'JWT_SECRET' or value) and (len(value.encode()) < 32 or value.startswith('REPLACE_')):
            raise ValueError(f'{key} requires a private secret of at least 32 UTF-8 bytes.')
    workers = int(environment.get('PNBP_WORKERS', '4'))
    port = int(environment.get('PNBP_PORT', '8000'))
    if not 1 <= workers <= 4 or not 1024 <= port <= 65535:
        raise ValueError('Use 1–4 workers and a port from 1024 to 65535.')
    if not environment.get('PNBP_ALLOWED_HOSTS'):
        raise ValueError('Configure an explicit PNBP_ALLOWED_HOSTS allowlist.')
    return ['gunicorn', 'main:api', '--no-control-socket', '--workers', str(workers),
            '--worker-class', 'uvicorn_worker.UvicornWorker', '--bind', f'127.0.0.1:{port}',
            '--forwarded-allow-ips', '127.0.0.1', '--timeout', '30', '--graceful-timeout', '30',
            '--access-logfile', '-']


if __name__ == '__main__':
    try:
        arguments = command(os.environ, uid=os.geteuid(), state=Path('/var/lib/pretty-notebook'))
    except (ValueError, OSError):
        sys.exit('Container configuration is invalid; check private state ownership, profile and secret settings.')
    os.umask(0o077)
    os.execvp(arguments[0], arguments)
