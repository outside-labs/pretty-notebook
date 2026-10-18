"""Bounded loopback health check; no credentials or state contents are printed."""

import json
import os
from urllib.request import Request, urlopen


def check():
    port = int(os.environ.get('PNBP_PORT', '8000'))
    host = os.environ.get('PNBP_ALLOWED_HOSTS', '127.0.0.1').split(',')[0].strip()
    with urlopen(Request(f'http://127.0.0.1:{port}/healthz', headers={'Host': host}), timeout=3) as response:
        if response.status != 200 or json.loads(response.read(4096)) != {'status': 'ok'}:
            raise ValueError('Unhealthy storage.')


if __name__ == '__main__':
    try:
        check()
    except (OSError, ValueError):
        raise SystemExit(1) from None
