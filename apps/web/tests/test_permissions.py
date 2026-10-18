"""Permission boundaries are checked against live state on every request."""

from datetime import UTC, datetime, timedelta
import hashlib
from fastapi.testclient import TestClient
from main import create_app
from tortoise import connections


def sql(client, statement, parameters=()):
    async def execute():
        return await connections.get('default').execute_query_dict(statement, list(parameters))
    return client.portal.call(execute)


def account(client, owner, role='reader', notebook='default', scopes=('read',)):
    response = client.post('/api/users', headers=owner, json={'username': role, 'password_hash': 'a sufficiently long password'})
    assert response.status_code == 200
    user_id = response.json()['id']
    assert client.put(f'/api/users/{user_id}/role', headers=owner, json={'role': role}).status_code == 200
    assert client.put(f'/api/users/{user_id}/grants', headers=owner, json={'notebook': notebook, 'permissions': scopes}).status_code == 200
    token = client.post('/api/token', data={'username': role, 'password': 'a sufficiently long password'}).json()['access_token']
    return user_id, {'Authorization': 'Bearer ' + token}


def test_reader_and_ungranted_editor_cannot_use_administrative_or_publishing_routes(client, auth_headers, layout_payload):
    reader, headers = account(client, auth_headers)
    for method, path, kwargs in [
        ('GET', '/api/publishments', {}), ('GET', '/api/images', {}),
        ('GET', '/api/publishing/inventory', {}),
        ('GET', '/api/forms/contact/submissions', {}),
        ('POST', '/api/layout', {'json': layout_payload}),
        ('POST', '/api/publishment', {'json': {'name': 'test', 'content': 'body'}}),
        ('POST', '/api/image', {'files': {'file': ('test.png', b'png')}}),
        ('POST', '/api/routes/preview', {'json': []}),
        ('DELETE', '/api/publishment/test.html', {}),
        ('PUT', '/api/appearance/stylesheet', {'content': 'body{}'}),
        ('POST', '/api/favicon', {'files': {'file': ('test.png', b'png')}}),
    ]:
        assert client.request(method, path, headers=headers, **kwargs).status_code == 403, path
    assert client.put(f'/api/users/{reader}/role', headers=headers, json={'role': 'owner'}).status_code == 403
    _, editor = account(client, auth_headers, role='editor', scopes=())
    assert client.get('/api/publishing/inventory', headers=editor).status_code == 403
    assert client.put(f'/api/users/{reader}/grants', headers=auth_headers, json={'permissions': []}).status_code == 200


def test_editor_grants_and_revocation_are_live(client, auth_headers):
    user_id, headers = account(client, auth_headers, role='editor', scopes=('read', 'publish'))
    assert client.get('/api/publishing/inventory', headers=headers).status_code == 200
    assert client.get('/api/publishing/inventory', headers={**headers, 'X-PNBP-Notebook': 'other'}).status_code == 403
    assert client.get('/api/forms/contact/submissions', headers=headers).status_code == 403
    client.put(f'/api/users/{user_id}/grants', headers=auth_headers, json={'permissions': []})
    assert client.get('/api/publishing/inventory', headers=headers).status_code == 403
    assert client.put('/api/users/999/grants', headers=auth_headers, json={'permissions': []}).status_code == 404
    assert client.put('/api/users/999/role', headers=auth_headers, json={'role': 'reader'}).status_code == 404
    assert client.put('/api/users/1/role', headers=auth_headers, json={'role': 'reader'}).status_code == 409


def test_script_credentials_are_narrow_hashed_revocable_and_bounded(client, auth_headers):
    created = client.post('/api/credentials', headers=auth_headers, json={'scopes': ['publish'], 'notebook': 'default'})
    assert created.status_code == 201, created.text
    token = created.json()['access_token']
    stored = sql(client, 'SELECT * FROM pnbp_credentials')[0]
    assert stored['digest'] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(stored)
    script = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/publishing/inventory', headers=script).status_code == 200
    assert client.get('/api/publishing/inventory', headers={**script, 'X-PNBP-Notebook': 'other'}).status_code == 403
    assert client.get('/api/forms/contact/submissions', headers=script).status_code == 403
    assert client.post('/api/users/me', headers=script, json={'password_hash': 'another long password'}).status_code == 403
    assert client.post('/api/credentials', headers=script, json={'scopes': ['site']}).status_code == 403
    assert 'digest' not in client.get('/api/credentials', headers=auth_headers).text
    assert client.delete(f"/api/credentials/{stored['id']}", headers=auth_headers).status_code == 204
    assert client.get('/api', headers=script).status_code == 401
    assert client.get('/api', headers={'Authorization': 'Bearer pnbp_unknown'}).status_code == 401


def test_expiry_password_reset_and_role_changes_revoke_scripts(client, auth_headers):
    _, reader = account(client, auth_headers)
    assert client.post('/api/credentials', headers=reader, json={'scopes': ['publish']}).status_code == 403
    token = client.post('/api/credentials', headers=auth_headers, json={'scopes': ['publish']}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    sql(client, 'UPDATE pnbp_credentials SET expires_at=?', [(datetime.now(UTC) - timedelta(seconds=1)).isoformat()])
    assert client.get('/api', headers=headers).status_code == 401
    sql(client, 'UPDATE pnbp_credentials SET expires_at=?', [(datetime.now(UTC) + timedelta(days=1)).isoformat()])
    assert client.post('/api/users/me', headers=auth_headers, json={'password_hash': 'another long password'}).status_code == 200
    assert client.get('/api', headers=headers).status_code == 401


def test_owner_is_a_role_and_missing_role_denies_privilege(client, auth_headers, layout_payload):
    user_id, editor = account(client, auth_headers, role='editor')
    assert client.put(f'/api/users/{user_id}/role', headers=auth_headers, json={'role': 'owner'}).status_code == 200
    assert client.post('/api/layout', headers=editor, json=layout_payload).status_code == 201
    assert client.put('/api/appearance/stylesheet', headers=editor, content='body { color: red; }').status_code == 204
    assert client.put('/api/users/1/role', headers=auth_headers, json={'role': 'reader'}).status_code == 200
    assert client.get('/api/publishing/inventory', headers=auth_headers).status_code == 403
    sql(client, 'DELETE FROM pnbp_roles WHERE user_id=?', [user_id])
    assert client.get('/api/publishing/inventory', headers=editor).status_code == 403


def test_permissions_survive_restart_and_legacy_migration(tmp_path, web_storage, root_credentials, bootstrap_headers):
    from test_schema import seed_legacy, token
    database = tmp_path / 'permissions.db'
    seed_legacy(database, root_credentials)
    headers = {'Authorization': 'Bearer ' + token('existing-token-state')}
    with TestClient(create_app(db_url=f'sqlite://{database}')) as client:
        roles = sql(client, 'SELECT * FROM pnbp_roles ORDER BY user_id')
        assert roles == [{'user_id': 1, 'role': 'owner'}, {'user_id': 4, 'role': 'editor'}]
        client.put('/api/users/4/grants', headers=headers, json={'notebook': 'default', 'permissions': []})
    with TestClient(create_app(db_url=f'sqlite://{database}')) as client:
        assert sql(client, 'SELECT * FROM pnbp_grants WHERE user_id=4') == []
        assert client.get('/api/publishing/inventory', headers=headers).status_code == 200
