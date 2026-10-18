"""Independent writers cannot mutate or inventory another notebook's state."""

import hashlib
import sqlite3
from contextlib import closing
from uuid import uuid4

from fastapi.testclient import TestClient
from main import create_app
from api import catalog, permissions, schema
from test_permissions import sql
from test_publishing_client import publishing_transport


def writer(client, owner, name):
    user = client.post('/api/users', headers=owner, json={'username': name, 'password_hash': 'a sufficiently long password'}).json()
    assert client.put(f"/api/users/{user['id']}/role", headers=owner, json={'role': 'editor'}).status_code == 200
    token = client.post('/api/token', data={'username': name, 'password': 'a sufficiently long password'}).json()['access_token']
    return user['id'], {'Authorization': 'Bearer ' + token}


def create(client, owner, slug, user_id):
    response = client.post('/api/notebooks', headers=owner, json={'slug': slug, 'owner_id': user_id})
    assert response.status_code == 201, response.text
    return response.json()


def payload(name, text='body'):
    return {'name': name, 'content': text, 'source_hash': 'a' * 64,
            'rendered_hash': hashlib.sha256(text.encode()).hexdigest(), 'renderer_fingerprint': 'b' * 64}


def test_two_owners_identical_names_images_and_scoped_pruning(client, auth_headers, web_storage):
    a_id, a = writer(client, auth_headers, 'alpha-writer')
    b_id, b = writer(client, auth_headers, 'beta-writer')
    alpha = create(client, auth_headers, 'alpha', a_id)
    beta = create(client, auth_headers, 'beta', b_id)
    a = {**a, 'X-PNBP-Notebook': 'alpha'}
    b = {**b, 'X-PNBP-Notebook': 'beta'}
    for headers, slug, text in ((a, 'alpha', 'Alpha body'), (b, 'beta', 'Beta body')):
        result = client.put('/api/publishing/publication', headers={**headers, 'If-None-Match': '*'}, json=payload('n/' + slug + '/same', text))
        assert result.status_code == 201, result.text
        assert client.post('/api/image', headers=headers, files={'file': ('same.png', b'\x89PNG\r\n\x1a\n' + text.encode())}).status_code == 201
    assert client.get('/api/publishments', headers=a).json()[0]['pub_name'] == 'n/alpha/same.html'
    inventory = client.get('/api/publishing/inventory', headers=a).json()
    assert inventory['notebook_id'] == alpha['id'] != beta['id']
    assert [entry['pub_name'] for entry in inventory['pages']] == ['n/alpha/same.html']
    assert [entry['name'] for entry in inventory['images']] == ['same.png']
    assert 'Beta body' not in str(inventory)
    assert client.get('/api/publishing/inventory', headers={**a, 'X-PNBP-Notebook': 'beta'}).status_code == 403
    assert client.post('/api/publishment', headers=a, json={'name': 'n/beta/same', 'content': 'hijack'}).status_code == 409
    assert client.delete('/api/publishment/n/beta/same.html', headers=a).status_code == 409
    assert client.delete('/api/publishing/publication/n/beta/same', headers={**a, 'If-Match': inventory['pages'][0]['etag']}).status_code == 409
    assert client.delete('/api/publishing/publication/n/alpha/same', headers={**a, 'If-Match': inventory['pages'][0]['etag']}).status_code == 200
    assert 'Beta body' in client.get('/n/beta/same').text
    assert client.get('/n/alpha/same').status_code == 404
    assert client.get('/static/imgs/n/alpha/same.png').content.endswith(b'Alpha body')
    assert client.get('/static/imgs/n/beta/same.png').content.endswith(b'Beta body')
    assert not client.get('/api/publishments', headers=auth_headers).json()
    assert not client.get('/api/images', headers=auth_headers).json()
    assert client.post('/api/publishment', headers=auth_headers, json={'name': 'n/beta/same', 'content': 'hijack'}).status_code == 409
    assert [row['slug'] for row in client.get('/api/notebooks', headers=a).json()] == ['alpha']
    assert len(client.get('/api/notebooks', headers=auth_headers).json()) == 3
    assert (web_storage.images / 'n/alpha/same.png').read_bytes() != (web_storage.images / 'n/beta/same.png').read_bytes()


def test_notebook_claim_validation_namespace_aliases_and_unknown_notebook(client, auth_headers):
    user_id, headers = writer(client, auth_headers, 'writer')
    assert client.post('/api/notebooks', headers=headers, json={'slug': 'alpha', 'owner_id': user_id}).status_code == 403
    assert client.post('/api/notebooks', headers=auth_headers, json={'slug': 'default', 'owner_id': 1}).status_code == 409
    assert client.post('/api/notebooks', headers=auth_headers, json={'slug': 'alpha', 'owner_id': 999}).status_code == 422
    assert client.post('/api/notebooks', headers=auth_headers, json={'slug': '../escape', 'owner_id': 1}).status_code == 422
    assert client.get('/api/publishing/inventory', headers={**auth_headers, 'X-PNBP-Notebook': 'unknown'}).status_code == 404
    assert client.post('/api/publishment', headers=auth_headers, json={'name': 'n/legacy/old', 'content': 'existing'}).status_code == 201
    assert client.post('/api/notebooks', headers=auth_headers, json={'slug': 'legacy', 'owner_id': user_id}).status_code == 409
    create(client, auth_headers, 'alpha', user_id)
    assert client.post('/api/notebooks', headers=auth_headers, json={'slug': 'alpha', 'owner_id': user_id}).status_code == 409
    scoped = {**headers, 'X-PNBP-Notebook': 'alpha'}
    for change in ({'name': 'outside'}, {'name': 'n/alpha/same', 'aliases': ['/outside']}, {'name': 'n/alpha/same', 'previous_name': 'outside'}):
        assert client.post('/api/publishment', headers=scoped, json={'content': 'body', **change}).status_code == 409
    preview = client.post('/api/routes/preview', headers=scoped, json=[{'name': 'outside'}])
    assert preview.status_code == 200 and not preview.json()['valid']
    reader = client.post('/api/users', headers=auth_headers, json={'username': 'reader', 'password_hash': 'a sufficiently long password'}).json()
    assert client.post('/api/notebooks', headers=auth_headers, json={'slug': 'reader-book', 'owner_id': reader['id']}).status_code == 422


def test_notebook_storage_failures_and_symlinks_do_not_claim_ownership(client, auth_headers, web_storage, monkeypatch):
    outside = web_storage.images.parent / 'outside'
    outside.mkdir()
    (web_storage.images / 'n').symlink_to(outside, target_is_directory=True)
    response = client.post('/api/notebooks', headers=auth_headers, json={'slug': 'alpha', 'owner_id': 1})
    assert response.status_code == 503
    assert len(client.get('/api/notebooks', headers=auth_headers).json()) == 1
    (web_storage.images / 'n').unlink()
    create(client, auth_headers, 'alpha', 1)
    scoped = {**auth_headers, 'X-PNBP-Notebook': 'alpha'}
    (web_storage.images / 'n/alpha').rmdir()
    assert client.get('/api/publishing/inventory', headers=scoped).json()['images'] == []
    assert client.get('/api/images', headers=scoped).json() == []
    # A failed upload cannot accidentally fall back to the default image root.
    assert client.post('/api/image', headers=scoped, files={'file': ('safe.png', b'\x89PNG\r\n\x1a\nbody')}).status_code == 500
    assert not (web_storage.images / 'safe.png').exists()


def test_ownership_and_partial_publications_survive_restart(tmp_path, web_storage, root_credentials, bootstrap_headers):
    database = tmp_path / 'owners.db'
    with TestClient(create_app(db_url=f'sqlite://{database}')) as client:
        client.post('/api/users', headers=bootstrap_headers, json=root_credentials)
        token = client.post('/api/token', data={'username': root_credentials['username'], 'password': root_credentials['password_hash']}).json()['access_token']
        owner = {'Authorization': 'Bearer ' + token}
        user_id, headers = writer(client, owner, 'writer')
        record = create(client, owner, 'alpha', user_id)
        scoped = {**headers, 'X-PNBP-Notebook': 'alpha'}
        assert client.post('/api/publishment', headers=scoped, json={'name': 'n/alpha/one', 'content': 'Saved before interruption'}).status_code == 201
        assert client.post('/api/publishment', headers=scoped, json={'name': 'bad', 'content': 'Rejected'}).status_code == 409
    with TestClient(create_app(db_url=f'sqlite://{database}')) as client:
        assert client.get('/api/notebooks', headers=headers).json() == [record]
        assert len(client.get('/api/publishments', headers=scoped).json()) == 1
        assert client.get('/api/publishments', headers=headers).status_code == 403
        assert 'Saved before interruption' in client.get('/n/alpha/one').text
        assert sql(client, "SELECT owner_id FROM pnbp_notebooks WHERE slot='default'")[0]['owner_id'] == 1


def test_upgrade_existing_catalog_preserves_ids_revisions_and_references(tmp_path, web_storage, root_credentials):
    from test_schema import seed_legacy, token
    database = tmp_path / 'upgrade.db'
    seed_legacy(database, root_credentials)
    identity = str(uuid4())
    with closing(sqlite3.connect(database)) as connection:
        for statements in (catalog.CATALOG_SCHEMA, permissions.PERMISSION_SCHEMA):
            for statement in statements:
                connection.execute(statement)
        connection.execute(schema.HISTORY_SCHEMA)
        for version in range(1, 4):
            connection.execute('INSERT INTO pnbp_schema_migrations (version,name,applied_at) VALUES (?,?,?)', [version, schema.MIGRATION_NAMES[version], '2026-10-18'])
        connection.execute('INSERT INTO pnbp_notebooks VALUES (?,?)', ['default', identity])
        digest = catalog._write_blob(web_storage.pages / '.blobs', 'Legacy body')
        connection.execute("INSERT INTO pnbp_notes VALUES ('note-id',?,'/legacy','[]','Legacy','public',1)", [identity])
        connection.execute("INSERT INTO pnbp_revisions VALUES ('note-id',1,?,NULL,?,NULL,'[]','2026-10-18')", [digest, digest])
        connection.commit()
    with TestClient(create_app(db_url=f'sqlite://{database}')) as client:
        assert client.app.state.schema_migration['version'] == schema.CURRENT_VERSION
        assert sql(client, 'PRAGMA foreign_key_check') == []
        assert sql(client, 'PRAGMA foreign_keys') == [{'foreign_keys': 1}]
        assert sql(client, "SELECT * FROM pnbp_notebooks WHERE slot='default'")[0] == {'slot': 'default', 'id': identity, 'owner_id': 1}
        assert sql(client, 'SELECT id,current_revision FROM pnbp_notes') == [{'id': 'note-id', 'current_revision': 1}]
        assert 'Legacy body' in client.get('/legacy').text
        create(client, {'Authorization': 'Bearer ' + token('existing-token-state')}, 'alpha', 4)


def test_installed_client_publishes_and_prunes_only_its_notebook(tmp_path, client, auth_headers, publishing_transport):
    from pretty_notebook import Notebook
    user_id, headers = writer(client, auth_headers, 'writer')
    create(client, auth_headers, 'alpha', user_id)
    create(client, auth_headers, 'beta', 1)
    assert client.post('/api/publishment', headers={**auth_headers, 'X-PNBP-Notebook': 'beta'}, json={'name': 'n/beta/same', 'content': 'Preserve beta'}).status_code == 201
    root = tmp_path / 'local'
    root.mkdir()
    (root / 'same.md').write_text('#public\nAlpha client body')
    nb = Notebook(root, settings={'API_BASE': str(client.base_url).rstrip('/'), 'ROUTE_MODE': 'namespaced', 'NOTEBOOK_SLUG': 'alpha', 'SERVER_NOTEBOOK': 'alpha'}, api_token=headers['Authorization'].split(' ', 1)[1], settings_file='off')
    nb.post_commits_to_web_api(mode='checked', prune=True)
    assert 'Alpha client body' in client.get('/n/alpha/same').text
    assert 'Preserve beta' in client.get('/n/beta/same').text
    nb.post_commits_to_web_api(mode='checked', prune=True)
    assert sql(client, "SELECT current_revision FROM pnbp_notes WHERE canonical_route='/n/alpha/same'") == [{'current_revision': 1}]
