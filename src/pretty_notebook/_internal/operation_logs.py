"""Bounded local operation receipts containing no note text, names or secrets."""

from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
import logging
import os
import sqlite3
from uuid import uuid4

OPERATIONS = frozenset({'collect', 'flush', 'publish', 'prune', 'image'})
MAX_EVENTS = 10_000
RETENTION_DAYS = 30
LOCAL_SCHEMA = '''CREATE TABLE IF NOT EXISTS operation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
)'''


def _path(root):
    state = Path(root).absolute() / '.pnbp'
    path = state / 'operations.sqlite3'
    if state.is_symlink() or path.is_symlink():
        raise ValueError('Operation logs must not use symlinks.')
    return state, path


@contextmanager
def _database(root):
    state, path = _path(root)
    state.mkdir(mode=0o700, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not path.is_file():
            raise ValueError('Operation logs require a regular database file.')
    else:
        os.close(descriptor)
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.row_factory = sqlite3.Row
        with connection:
            connection.execute(LOCAL_SCHEMA)
            yield connection


def start(root, operation):
    if operation not in OPERATIONS:
        raise ValueError('Unknown operation type.')
    operation_id = str(uuid4())
    now = datetime.now(UTC)
    with _database(root) as connection:
        connection.execute('DELETE FROM operation_events WHERE started_at<?', [(now - timedelta(days=RETENTION_DAYS)).isoformat()])
        connection.execute('DELETE FROM operation_events WHERE id IN (SELECT id FROM operation_events ORDER BY id DESC LIMIT -1 OFFSET ?)', [MAX_EVENTS - 1])
        connection.execute('INSERT INTO operation_events (operation_id,operation,outcome,started_at) VALUES (?,?,?,?)', [operation_id, operation, 'started', now.isoformat()])
    return operation_id


def finish(root, operation_id, outcome):
    with _database(root) as connection:
        connection.execute('UPDATE operation_events SET outcome=?,finished_at=? WHERE operation_id=?', [outcome, datetime.now(UTC).isoformat(), operation_id])


@contextmanager
def operation(root, name):
    """Commit the start before acting; leave an interrupted receipt on a crash."""
    operation_id = start(root, name)
    try:
        yield operation_id
    except BaseException:
        _finish_safely(root, operation_id, 'failed')
        raise
    else:
        _finish_safely(root, operation_id, 'succeeded')


def _finish_safely(root, operation_id, outcome):
    try:
        finish(root, operation_id, outcome)
    except Exception:
        # A receipt-finalization failure must not disguise a completed save or
        # replace the original operation exception with a storage exception.
        logging.getLogger(__name__).error('Could not finalize an operation receipt.')


def read(root, *, limit=100, before=0):
    if type(limit) is not int or not 1 <= limit <= 100 or type(before) is not int or before < 0:
        raise ValueError('Logs require limit 1–100 and a nonnegative before cursor.')
    _, path = _path(root)
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute('SELECT id,operation_id,operation,outcome,started_at,finished_at FROM operation_events WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT ?', [before, before, limit])]
