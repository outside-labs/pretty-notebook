"""Bounded local receipts and authenticated server operation-log client."""

import requests
from pretty_notebook._internal.operation_logs import read


def operation_logs(notebook, *, remote=False, limit=100, before=0):
    if type(limit) is not int or not 1 <= limit <= 100 or type(before) is not int or before < 0:
        raise ValueError('Logs require limit 1–100 and a nonnegative before cursor.')
    if not remote:
        return read(notebook.NOTE_PATH, limit=limit, before=before)
    response = notebook._api_request(requests.get, '/api/logs', headers=notebook.get_headers(), params={'limit': limit, 'before': before})
    data = response.json()
    allowed = {'id', 'operation_id', 'user_id', 'operation', 'outcome', 'status_code', 'started_at', 'finished_at'}
    if not isinstance(data, list) or len(data) > limit or any(not isinstance(row, dict) or set(row) != allowed for row in data):
        raise ValueError('Invalid bounded server operation-log response.')
    return data
