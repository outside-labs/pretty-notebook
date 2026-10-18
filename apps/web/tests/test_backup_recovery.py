"""A stopped-site checkpoint reopens with content, accounts and revocations intact."""

from importlib.metadata import version
import os
from pathlib import Path
import pwd

from fastapi.testclient import TestClient

from api import layout_api, publish_api
from test_notebook_ownership import writer, create
from test_permissions import sql
from main import create_app
from pretty_notebook._internal import backups
from pretty_notebook._internal.deployment import DeploySpec, bundle


def test_verified_restore_retains_all_persistent_behavior(tmp_path, monkeypatch, web_storage,
                                                         root_credentials, bootstrap_headers, layout_payload):
    original = tmp_path / 'original'
    original.mkdir(mode=0o700)

    def paths(root):
        monkeypatch.setattr(publish_api, 'PUB_PATH', root / 'pages')
        monkeypatch.setattr(publish_api, 'IMG_PATH', root / 'images')
        monkeypatch.setattr(layout_api, 'WEB_SETTINGS_PATH', root / 'web-settings.json')

    paths(original)
    with TestClient(create_app(db_url=f'sqlite://{original / "db.sqlite3"}')) as client:
        assert client.post('/api/users', json=root_credentials, headers=bootstrap_headers).status_code == 200
        def login(password):
            response = client.post('/api/token', data={'username': 'owner', 'password': password})
            assert response.status_code == 200
            return {'Authorization': 'Bearer ' + response.json()['access_token']}
        revoked = login(root_credentials['password_hash'])
        assert client.post('/api/users/me', headers=revoked, json={'password_hash': 'replacement-password-123'}).status_code == 200
        current = login('replacement-password-123')
        assert client.get('/api/users/me', headers=revoked).status_code == 401
        layout_payload['TITLE'] = 'Recovered title'
        assert client.post('/api/layout', headers=current, json=layout_payload).status_code == 201
        assert client.post('/api/publishment', headers=current, json={'name': 'retained', 'content': '<h1>Recovered body</h1>'}).status_code == 201
        image = b'\x89PNG\r\n\x1a\nsynthetic-image'
        assert client.post('/api/image', headers=current, files={'file': ('retained.png', image, 'image/png')}).status_code == 201
        assert client.post('/forms/contact', data={'email_address': 'fixture@example.test', 'email_message': 'Recovered inbox'}, follow_redirects=False).status_code == 303
        writer_id, writer_headers = writer(client, current, 'notebook-writer')
        second_id, second_headers = writer(client, current, 'second-writer')
        alpha = create(client, current, 'alpha', writer_id)
        create(client, current, 'beta', second_id)
        alpha_headers = {**writer_headers, 'X-PNBP-Notebook': 'alpha'}
        beta_headers = {**second_headers, 'X-PNBP-Notebook': 'beta'}
        for scoped, slug in ((alpha_headers, 'alpha'), (beta_headers, 'beta')):
            assert client.post('/api/publishment', headers=scoped, json={'name': f'n/{slug}/same', 'content': f'Recovered {slug}'}).status_code == 201
            assert client.post('/api/image', headers=scoped, files={'file': ('same.png', image + slug.encode(), 'image/png')}).status_code == 201
        script = client.post('/api/credentials', headers=writer_headers, json={'scopes': ['publish', 'logs'], 'notebook': 'alpha'}).json()['access_token']
        revoked_script = client.post('/api/credentials', headers=writer_headers, json={'scopes': ['publish'], 'notebook': 'alpha'}).json()['access_token']
        credential_id = client.get('/api/credentials', headers=writer_headers).json()[-1]['id']
        assert client.delete(f'/api/credentials/{credential_id}', headers=writer_headers).status_code == 204
        client.put(f'/api/users/{second_id}/grants', headers=current, json={'notebook': 'beta', 'permissions': []})
        log_count = len(client.get('/api/logs', headers=alpha_headers).json())
    spec = DeploySpec('a' * 40, 'notes.example.com', checkout=tmp_path / 'checkout', data_dir=original,
                      env_file=tmp_path / 'environment', backup_dir=tmp_path / 'checkpoints',
                      user=pwd.getpwuid(os.getuid()).pw_name)
    spec.env_file.write_text(bundle(spec)['environment.example'].replace('REPLACE_WITH_A_PRIVATE_RANDOM_SECRET', os.environ['JWT_SECRET']).replace('REPLACE_WITH_A_DIFFERENT_PRIVATE_RANDOM_SECRET', os.environ['PNBP_BOOTSTRAP_TOKEN']))
    spec.env_file.chmod(0o600)
    # The TestClient lifespan has closed; process-manager checks are covered in library tests.
    monkeypatch.setattr(backups, '_require_stopped', lambda *args, **kwargs: None)
    monkeypatch.setattr(backups, '_code_identity', lambda *args: {'revision': spec.revision, 'version': version('pretty-notebook')})
    checkpoint = tmp_path / 'checkpoint'
    backups.backup_site(spec, checkpoint, apply=True)
    result = backups.restore_site(spec, checkpoint, tmp_path / 'recovered', apply=True)
    restored = Path(result['state'])
    paths(restored)
    with TestClient(create_app(db_url=f'sqlite://{restored / "db.sqlite3"}')) as client:
        assert client.get('/healthz').status_code == 200
        assert 'Recovered title' in client.get('/').text
        assert 'Recovered body' in client.get('/retained').text
        assert client.get('/static/imgs/retained.png').content == image
        assert client.get('/api/users/me', headers=current).json()['username'] == 'owner'
        assert client.get('/api/users/me', headers=revoked).status_code == 401
        messages = client.get('/api/forms/contact/submissions', headers=current)
        assert messages.status_code == 200 and messages.json()[0]['payload']['email_message'] == 'Recovered inbox'
        assert client.post('/api/users', json={'username': 'second', 'password_hash': 'second-password-123'}, headers=bootstrap_headers).status_code == 401
        assert client.get('/api/notebooks', headers=writer_headers).json() == [alpha]
        assert 'Recovered alpha' in client.get('/n/alpha/same').text
        assert 'Recovered beta' in client.get('/n/beta/same').text
        assert client.get('/static/imgs/n/alpha/same.png').content == image + b'alpha'
        assert client.get('/static/imgs/n/beta/same.png').content == image + b'beta'
        assert client.get('/api/publishing/inventory', headers=beta_headers).status_code == 403
        assert client.get('/api/publishing/inventory', headers={**writer_headers, 'X-PNBP-Notebook': 'beta'}).status_code == 403
        script_headers = {'Authorization': 'Bearer ' + script, 'X-PNBP-Notebook': 'alpha'}
        inventory = client.get('/api/publishing/inventory', headers=script_headers).json()
        assert inventory['notebook_id'] == alpha['id']
        assert [entry['pub_name'] for entry in inventory['pages']] == ['n/alpha/same.html']
        assert len(client.get('/api/logs', headers=script_headers).json()) == log_count
        assert client.get('/api/publishing/inventory', headers={'Authorization': 'Bearer ' + revoked_script, 'X-PNBP-Notebook': 'alpha'}).status_code == 401
        assert client.delete('/api/publishment/n/beta/same.html', headers=script_headers).status_code == 409
        assert client.post('/api/publishment', headers=script_headers, json={'name': 'n/alpha/same', 'content': 'Updated after restore'}).status_code == 201
        assert 'Updated after restore' in client.get('/n/alpha/same').text
        assert 'Recovered beta' in client.get('/n/beta/same').text
        assert sql(client, 'PRAGMA foreign_key_check') == []
    assert (original / 'db.sqlite3').exists() and (checkpoint / 'manifest.json').exists()
