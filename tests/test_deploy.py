import json
import os
import pwd
import shutil
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from cli_runner import CliRunner
from pretty_notebook.cli import cli
from pretty_notebook._internal.deployment import DeploySpec, bundle, write_bundle, check_environment, check_deployment

REVISION = 'a' * 40


@pytest.mark.parametrize('changes', [
    {'revision': 'main'}, {'domain': 'notes.example.com;touch /tmp/x'}, {'domain': '*.example.com'},
    {'checkout': Path('/opt/name%specifier')}, {'checkout': Path('/opt/../etc/name')},
    {'data_dir': Path('/opt/pretty-notebook/state')}, {'env_file': Path('/var/lib/pretty-notebook/environment')},
    {'workers': 5}, {'workers': True}, {'port': 80}, {'service': 'name\nExecStart=bad'},
    {'user': 'root;bad'}, {'user': 'root'}, {'prefix': '/bad?query'}, {'python': 'python3.12'},
])
def test_rejects_unsafe_or_unsupported_deployment_inputs(changes):
    with pytest.raises(ValueError): DeploySpec(**{'revision': REVISION, 'domain': 'notes.example.com', **changes})


def test_bundle_is_deterministic_and_preserves_owner_edits(tmp_path):
    spec = DeploySpec(REVISION, 'notes.example.com', prefix='/notes')
    first = write_bundle(spec, tmp_path)
    assert write_bundle(spec, tmp_path) == first
    unit = (tmp_path / 'pretty-notebook.service').read_text()
    assert '--workers 4' in unit and '--bind 127.0.0.1:8000' in unit
    assert '--no-control-socket' in unit
    assert 'User=pretty-notebook' in unit and 'UMask=0077' in unit
    proxy = (tmp_path / 'nginx.conf').read_text()
    assert 'location /notes/' in proxy and 'https://notes.example.com$request_uri' in proxy
    assert 'proxy_set_header X-Forwarded-For $remote_addr;' in proxy
    manifest = json.loads((tmp_path / 'plan.json').read_text())
    assert manifest['spec']['revision'] == REVISION
    assert 'JWT_SECRET' not in json.dumps(manifest)
    (tmp_path / 'environment.example').write_text('Owner edits stay here')
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='already differs'): write_bundle(spec, tmp_path)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_cli_planning_never_opens_a_notebook_and_upgrade_only_writes_a_bundle(tmp_path, monkeypatch):
    def unexpected(): raise AssertionError('No notebook should be opened')
    monkeypatch.setattr('pretty_notebook.cli._open_notebook', unexpected)
    runner = CliRunner()
    args = ['--revision', REVISION, '--domain', 'notes.example.com']
    planned = runner.invoke(cli, ['deploy', 'plan', *args])
    assert planned.exit_code == 0, planned.output
    assert not list(tmp_path.iterdir())
    upgrade = runner.invoke(cli, ['deploy', 'upgrade', *args, '--output', str(tmp_path)])
    assert upgrade.exit_code == 0, upgrade.output
    script = (tmp_path / 'upgrade.sh').read_text()
    assert script.index('systemctl stop') < script.index('cp -a') < script.index('git_site checkout')
    assert 'checkpoint.py" record' in script and 'check_site --health' in script
    rollback = (tmp_path / 'rollback.sh').read_text()
    assert rollback.index('checkpoint.py" verify') < rollback.index('mv "$data_dir"')
    assert 'failed_state/state' in rollback
    for path in tmp_path.glob('*.sh'):
        subprocess.run(['bash', '-n', str(path)], check=True)


def environment(tmp_path, secret='s' * 32):
    path = tmp_path / 'environment'
    spec = DeploySpec(REVISION, 'notes.example.com', env_file=path)
    content = bundle(spec)['environment.example'].replace('REPLACE_WITH_A_PRIVATE_RANDOM_SECRET', secret).replace('REPLACE_WITH_A_DIFFERENT_PRIVATE_RANDOM_SECRET', 'b' * 32)
    path.write_text(content)
    path.chmod(0o600)
    return spec, path


def test_environment_validation_and_diagnostics_never_echo_secrets(tmp_path):
    spec, path = environment(tmp_path)
    assert check_environment(spec, require_bootstrap=True) == {'environment': 'ok'}
    path.write_text(path.read_text().replace('PNBP_BOOTSTRAP_TOKEN=' + 'b' * 32, 'PNBP_BOOTSTRAP_TOKEN='))
    assert check_environment(spec) == {'environment': 'ok'}
    with pytest.raises(ValueError, match='PNBP_BOOTSTRAP_TOKEN'): check_environment(spec, require_bootstrap=True)
    path.chmod(0o644)
    with pytest.raises(ValueError, match='private regular'): check_environment(spec)
    path.chmod(0o600)
    path.write_text(path.read_text() + '\nJWT_SECRET=private-secret-do-not-echo\n')
    result = CliRunner().invoke(cli, ['deploy', 'check', '--revision', REVISION, '--domain', spec.domain, '--env-file', str(path)])
    assert result.exit_code == 1
    assert 'private-secret-do-not-echo' not in result.output and 's' * 32 not in result.output


def test_checkpoint_verifies_database_and_detects_corrupt_files_before_restore(tmp_path):
    spec = DeploySpec(REVISION, 'notes.example.com')
    program = tmp_path / 'checkpoint.py'
    program.write_text(bundle(spec)['checkpoint.py'])
    checkpoint = tmp_path / 'checkpoint'
    state = checkpoint / 'state'
    state.mkdir(parents=True)
    with closing(sqlite3.connect(state / 'db.sqlite3')) as connection:
        connection.execute('CREATE TABLE content (value TEXT)')
        connection.execute("INSERT INTO content VALUES ('preserved')")
        connection.commit()
    (checkpoint / 'environment').write_text('synthetic-private-state')
    subprocess.run([sys.executable, str(program), 'record', str(checkpoint)], check=True)
    subprocess.run([sys.executable, str(program), 'verify', str(checkpoint)], check=True)
    (checkpoint / 'environment').write_text('changed')
    failed = subprocess.run([sys.executable, str(program), 'verify', str(checkpoint)], capture_output=True, text=True)
    assert failed.returncode != 0
    assert 'synthetic-private-state' not in failed.stderr and 'changed' not in failed.stderr


def test_diagnostics_check_real_revision_private_state_and_child_failures(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (checkout / 'apps/web').mkdir(parents=True)
    asset_check = checkout / 'apps/web/install_assets.py'
    asset_check.write_text('print("assets ok")\n')
    (checkout / '.gitignore').write_text('.venv/\n')
    subprocess.run(['git', 'init', str(checkout)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(checkout), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Example User', '-c', 'user.email=fixture@example.test', 'commit', '-m', 'fixture'], check=True, capture_output=True)
    revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run([sys.executable, '-m', 'venv', str(checkout / '.venv')], check=True)
    state = tmp_path / 'state'
    state.mkdir(mode=0o700)
    spec = DeploySpec(revision, 'notes.example.com', checkout=checkout, data_dir=state,
                      env_file=tmp_path / 'environment', backup_dir=tmp_path / 'backups',
                      user=pwd.getpwuid(os.getuid()).pw_name,
                      python=f'python{sys.version_info.major}.{sys.version_info.minor}')
    spec.env_file.write_text(bundle(spec)['environment.example'].replace('REPLACE_WITH_A_PRIVATE_RANDOM_SECRET', 's' * 32).replace('REPLACE_WITH_A_DIFFERENT_PRIVATE_RANDOM_SECRET', 'b' * 32))
    spec.env_file.chmod(0o600)
    assert check_deployment(spec)['assets'] == 'ok'
    state.chmod(0o755)
    with pytest.raises(ValueError, match='private directory'): check_deployment(spec)
    state.chmod(0o700)
    asset_check.write_text('raise SystemExit("synthetic-secret-do-not-echo")\n')
    with pytest.raises(ValueError, match='Checkout cleanliness') as failed: check_deployment(spec)
    assert 'synthetic-secret-do-not-echo' not in str(failed.value)


@pytest.mark.skipif(not shutil.which('systemd-analyze'), reason='Linux unit verifier is not available')
def test_generated_systemd_unit_passes_platform_parser(tmp_path):
    spec = DeploySpec(REVISION, 'notes.example.com', checkout=tmp_path / 'checkout', data_dir=tmp_path / 'state', env_file=tmp_path / 'environment', backup_dir=tmp_path / 'backups')
    executable = spec.checkout / '.venv/bin/gunicorn'
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    spec.data_dir.mkdir()
    unit = tmp_path / 'pretty-notebook.service'
    unit.write_text(bundle(spec)['pretty-notebook.service'])
    result = subprocess.run(['systemd-analyze', 'verify', str(unit)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which('nginx'), reason='nginx parser is not available')
def test_generated_nginx_config_passes_platform_parser(tmp_path):
    cert, key = tmp_path / 'certificate.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=notes.example.com', '-days', '1', '-out', str(cert), '-keyout', str(key)], check=True, capture_output=True)
    spec = DeploySpec(REVISION, 'notes.example.com', tls_cert=cert, tls_key=key, prefix='/notes')
    generated = bundle(spec)['nginx.conf']
    assert 'listen 80;' in generated and 'listen 443 ssl;' in generated
    # The validator binds listeners too; use private ephemeral ports in tests.
    with socket.socket() as http, socket.socket() as https:
        http.bind(('127.0.0.1', 0))
        https.bind(('127.0.0.1', 0))
        generated = generated.replace('listen 80;', f'listen 127.0.0.1:{http.getsockname()[1]};')
        generated = generated.replace('listen 443 ssl;', f'listen 127.0.0.1:{https.getsockname()[1]} ssl;')
    config = tmp_path / 'nginx.conf'
    config.write_text(f'error_log stderr;\npid {tmp_path}/nginx.pid;\nevents {{}}\nhttp {{ access_log off; client_body_temp_path {tmp_path}/body; proxy_temp_path {tmp_path}/proxy;\n' + generated + '\n}\n')
    result = subprocess.run(['nginx', '-t', '-p', str(tmp_path), '-c', str(config)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
