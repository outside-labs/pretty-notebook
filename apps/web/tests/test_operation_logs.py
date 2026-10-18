"""Server operation events enforce notebook grants, retention and redaction."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from main import create_app
from api import operation_logs, publish_api
from test_notebook_ownership import create, writer
from test_permissions import sql


def test_publication_failures_images_pruning_and_correlation_are_logged(client, auth_headers):
    correlation = str(uuid4())
    headers = {**auth_headers, 'X-PNBP-Operation-ID': correlation}
    response = client.post('/api/publishment', headers=headers, json={'name': 'secret-name', 'content': 'secret content'})
    assert response.status_code == 201
    assert response.headers['X-PNBP-Operation-ID'] == correlation
    assert client.post('/api/image', headers=headers, files={'file': ('private.png', b'not PNG')}).status_code == 400
    assert client.put('/api/publishing/publication', headers=headers, json={}).status_code == 422
    assert client.delete('/api/publishment/secret-name.html', headers=headers).status_code == 200
    rows = client.get('/api/logs', headers=auth_headers).json()
    assert len(rows) == 4
    assert [row['operation'] for row in rows] == ['prune', 'publish', 'image', 'publish']
    assert [row['outcome'] for row in rows] == ['succeeded', 'failed', 'failed', 'succeeded']
    assert {row['operation_id'] for row in rows} == {correlation}
    assert 'secret-name' not in str(rows) and 'secret content' not in str(rows) and 'private.png' not in str(rows)
    assert auth_headers['Authorization'] not in str(rows)
    assert client.get('/api/logs', headers=auth_headers, params={'limit': 1, 'before': rows[0]['id']}).json() == rows[1:2]
    assert client.get('/api/logs', headers=auth_headers, params={'limit': 101}).status_code == 422
    assert client.get('/api/logs').status_code == 401


def test_notebook_logs_enforce_live_scopes_and_never_include_siblings(client, auth_headers):
    user_id, headers = writer(client, auth_headers, 'writer')
    create(client, auth_headers, 'alpha', user_id)
    scoped = {**headers, 'X-PNBP-Notebook': 'alpha'}
    assert client.post('/api/publishment', headers=scoped, json={'name': 'n/alpha/one', 'content': 'body'}).status_code == 201
    assert client.get('/api/logs', headers=auth_headers).json() == []
    assert len(client.get('/api/logs', headers=scoped).json()) == 1
    assert client.get('/api/logs', headers=headers).status_code == 403
    token = client.post('/api/credentials', headers=headers, json={'scopes': ['logs'], 'notebook': 'alpha'}).json()['access_token']
    log_headers = {'Authorization': 'Bearer ' + token, 'X-PNBP-Notebook': 'alpha'}
    assert len(client.get('/api/logs', headers=log_headers).json()) == 1
    assert client.post('/api/publishment', headers=log_headers, json={'name': 'n/alpha/two', 'content': 'denied'}).status_code == 403
    assert len(client.get('/api/logs', headers=log_headers).json()) == 1
    client.put(f'/api/users/{user_id}/grants', headers=auth_headers, json={'notebook': 'alpha', 'permissions': []})
    assert client.get('/api/logs', headers=log_headers).status_code == 403
    assert client.post('/api/publishment', headers={'Authorization': 'Bearer invalid'}, json={'name': 'one', 'content': 'denied'}).status_code == 401
    assert client.post('/api/publishment', json={'name': 'one', 'content': 'denied'}).status_code == 401


def test_retention_and_start_failure_stop_before_publication(client, auth_headers, monkeypatch):
    monkeypatch.setattr(operation_logs, 'MAX_EVENTS', 2)
    for index in range(4):
        assert client.post('/api/publishment', headers=auth_headers, json={'name': f'note-{index}', 'content': 'body'}).status_code == 201
    assert len(client.get('/api/logs', headers=auth_headers).json()) == 2
    sql(client, 'UPDATE pnbp_operation_events SET started_at=?', [(datetime.now(UTC) - timedelta(days=31)).isoformat()])
    client.post('/api/publishment', headers=auth_headers, json={'name': 'recent', 'content': 'body'})
    assert len(client.get('/api/logs', headers=auth_headers).json()) == 1
    async def fail(*args):
        raise OSError('secret state path')
    monkeypatch.setattr(operation_logs, '_start', fail)
    result = client.post('/api/publishment', headers=auth_headers, json={'name': 'stopped', 'content': 'not saved'})
    assert result.status_code == 503 and 'secret state path' not in result.text
    assert client.get('/stopped').status_code == 404


def test_failed_operation_and_finalization_preserve_redacted_recovery_state(client, auth_headers, monkeypatch, caplog):
    original = publish_api.add_publishment
    async def failed_publication(*args, **kwargs):
        raise RuntimeError('private body and secret token')
    monkeypatch.setattr(publish_api, 'add_publishment', failed_publication)
    assert client.post('/api/publishment', headers=auth_headers, json={'name': 'failed', 'content': 'body'}).status_code == 500
    assert client.get('/api/logs', headers=auth_headers).json()[0]['outcome'] == 'failed'
    monkeypatch.setattr(publish_api, 'add_publishment', original)
    from tortoise import connections
    connection = connections.get('default')
    execute = connection.execute_query
    async def fail_finalization(statement, *args, **kwargs):
        if statement.startswith('UPDATE pnbp_operation_events'):
            raise RuntimeError('private database location')
        return await execute(statement, *args, **kwargs)
    monkeypatch.setattr(connection, 'execute_query', fail_finalization)
    result = client.post('/api/publishment', headers=auth_headers, json={'name': 'saved', 'content': 'Saved despite finalization failure'})
    assert result.status_code == 201
    assert 'Saved despite' in client.get('/saved').text
    rows = client.get('/api/logs', headers=auth_headers).json()
    assert rows[0]['outcome'] == 'started'
    assert 'private database location' not in caplog.text
    assert 'private body' not in str(rows)


def test_events_survive_restart_and_remote_client_pagination(tmp_path, web_storage, root_credentials, bootstrap_headers, monkeypatch):
    database = tmp_path / 'logs.db'
    with TestClient(create_app(db_url=f'sqlite://{database}')) as client:
        client.post('/api/users', headers=bootstrap_headers, json=root_credentials)
        token = client.post('/api/token', data={'username': root_credentials['username'], 'password': root_credentials['password_hash']}).json()['access_token']
        headers = {'Authorization': 'Bearer ' + token}
        assert client.post('/api/publishment', headers=headers, json={'name': 'one', 'content': 'body'}).status_code == 201
    with TestClient(create_app(db_url=f'sqlite://{database}')) as client:
        rows = client.get('/api/logs', headers=headers).json()
        assert len(rows) == 1 and rows[0]['outcome'] == 'succeeded'
        from pretty_notebook import Notebook
        from pretty_notebook.commands.logs import operation_logs as read_logs
        nb = Notebook(tmp_path, settings_file='off')
        monkeypatch.setattr(nb, '_api_request', lambda method, path, **kwargs: client.get(path, headers=headers, params=kwargs['params']))
        assert read_logs(nb, remote=True, limit=1) == rows
