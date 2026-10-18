"""Notebook-scoped operation events with bounded retention and redacted fields."""

from datetime import UTC, datetime, timedelta
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from tortoise import connections

from .auth_api import get_current_user
from .notebooks import notebook_record
from .permissions import authorize, require_permission
from pretty_notebook._internal.operation_logs import MAX_EVENTS, RETENTION_DAYS

router = APIRouter()
OPERATIONS_SCHEMA = (
    '''CREATE TABLE pnbp_operation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id TEXT NOT NULL,
        notebook_id TEXT NOT NULL REFERENCES pnbp_notebooks(id),
        user_id INTEGER REFERENCES user(id) ON DELETE SET NULL,
        operation TEXT NOT NULL CHECK(operation IN ('publish','image','prune')),
        outcome TEXT NOT NULL CHECK(outcome IN ('started','succeeded','failed')),
        status_code INTEGER,
        started_at TEXT NOT NULL,
        finished_at TEXT
    )''',
    'CREATE INDEX pnbp_operation_events_notebook_id ON pnbp_operation_events(notebook_id,id)',
)


async def _start(request, user, operation):
    slug = request.headers.get('X-PNBP-Notebook', 'default')
    record = await notebook_record(slug)
    try:
        operation_id = str(UUID(request.headers.get('X-PNBP-Operation-ID', '')))
    except ValueError:
        operation_id = str(uuid4())
    now = datetime.now(UTC)
    async with request.app.state.storage_lock:
        from tortoise.transactions import in_transaction
        async with in_transaction() as connection:
            await connection.execute_query('DELETE FROM pnbp_operation_events WHERE notebook_id=? AND started_at<?', [record['id'], (now - timedelta(days=RETENTION_DAYS)).isoformat()])
            await connection.execute_query('DELETE FROM pnbp_operation_events WHERE id IN (SELECT id FROM pnbp_operation_events WHERE notebook_id=? ORDER BY id DESC LIMIT -1 OFFSET ?)', [record['id'], MAX_EVENTS - 1])
            _, rows = await connection.execute_query('INSERT INTO pnbp_operation_events (operation_id,notebook_id,user_id,operation,outcome,started_at) VALUES (?,?,?,?,?,?) RETURNING id', [operation_id, record['id'], user.id, operation, 'started', now.isoformat()])
    return rows[0]['id'], operation_id


async def _finish(request, event_id, status_code):
    try:
        async with request.app.state.storage_lock:
            await connections.get('default').execute_query('UPDATE pnbp_operation_events SET outcome=?,status_code=?,finished_at=? WHERE id=?', ['succeeded' if status_code < 400 else 'failed', status_code, datetime.now(UTC).isoformat(), event_id])
    except Exception:
        logging.getLogger(__name__).error('Could not finalize a server operation receipt.')


async def audit_request(request, call_next):
    path = request.url.path.removeprefix(request.scope.get('root_path', ''))
    operation = None
    if request.method in {'POST', 'PUT'}:
        if path in {'/api/publishment', '/api/publishing/publication'}:
            operation = 'publish'
        elif path in {'/api/image', '/api/publishing/image'}:
            operation = 'image'
    elif request.method == 'DELETE' and path.startswith(('/api/publishment/', '/api/publishing/publication/')):
        operation = 'prune'
    if operation is None:
        return await call_next(request)
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.casefold() != 'bearer' or not token:
        return await call_next(request)
    try:
        user = await get_current_user(token)
        await authorize(user, 'publish', request.headers.get('X-PNBP-Notebook', 'default'))
        await notebook_record(request.headers.get('X-PNBP-Notebook', 'default'))
    except HTTPException:
        return await call_next(request)
    try:
        event_id, operation_id = await _start(request, user, operation)
    except Exception:
        return JSONResponse({'detail': 'Operation logging is unavailable; no publication was attempted.'}, status_code=503)
    try:
        response = await call_next(request)
    except BaseException:
        await _finish(request, event_id, 500)
        raise
    await _finish(request, event_id, response.status_code)
    response.headers['X-PNBP-Operation-ID'] = operation_id
    return response


@router.get('/api/logs')
async def list_logs(request: Request, limit: int = Query(100, ge=1, le=100), before: int = Query(0, ge=0), user=Depends(require_permission('logs'))):
    record = await notebook_record(request.headers.get('X-PNBP-Notebook', 'default'))
    return await connections.get('default').execute_query_dict('SELECT id,operation_id,user_id,operation,outcome,status_code,started_at,finished_at FROM pnbp_operation_events WHERE notebook_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT ?', [record['id'], before, before, limit])
