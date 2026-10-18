import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest
from cli_runner import CliRunner
from pretty_notebook.cli import cli
from pretty_notebook._internal.deployment import DeploySpec, bundle, write_bundle

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location('container_start', ROOT / 'apps/web/container/start.py')
startup = importlib.util.module_from_spec(specification)
specification.loader.exec_module(startup)
REVISION = 'a' * 40


def test_container_bundle_is_pinned_private_and_idempotent(tmp_path):
    spec = DeploySpec(REVISION, 'notes.example.com', prefix='/notes', workers=2)
    files = bundle(spec, profile='container')
    compose = json.loads(files['compose.json'])['services']['notebook']
    assert compose['image'].endswith(REVISION)
    assert compose['pull_policy'] == 'never' and compose['network_mode'] == 'host'
    assert compose['read_only'] and compose['user'] == '10001:10001'
    assert compose['volumes'][0]['bind']['create_host_path'] is False
    assert compose['env_file'][0]['format'] == 'raw'
    assert 'PNBP_WORKERS=2' in files['environment.example']
    assert 'PNBP_URL_PREFIX=/notes' in files['environment.example']
    assert '127.0.0.1:8000' in files['nginx.conf']
    output = tmp_path / 'bundle'
    first = write_bundle(spec, output, profile='container')
    assert write_bundle(spec, output, profile='container') == first
    subprocess.run(['bash', '-n', str(output / 'build.sh')], check=True)
    (output / 'compose.json').write_text('Existing custom configuration')
    with pytest.raises(ValueError, match='differs'):
        write_bundle(spec, output, profile='container')
    assert (output / 'compose.json').read_text() == 'Existing custom configuration'


def test_container_plan_cli_does_not_write_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ['deploy', 'plan', '--profile', 'container', '--revision', REVISION,
                                     '--domain', 'notes.example.com'])
    assert result.exit_code == 0, result.exception
    assert json.loads(result.output)['profile'] == 'container'
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match='Python 3.14'):
        bundle(DeploySpec(REVISION, 'notes.example.com', python='python3.11'), profile='container')


def test_startup_preserves_private_state_and_uses_loopback(tmp_path):
    state = tmp_path / 'state'
    state.mkdir(mode=0o700)
    existing = state / 'receipt'
    existing.write_text('Preserved')
    environment = {'JWT_SECRET': 'x' * 32, 'PNBP_ALLOWED_HOSTS': 'notes.example.com', 'PNBP_PORT': '8765'}
    command = startup.command(environment, uid=os.getuid(), state=state)
    assert command[command.index('--bind') + 1] == '127.0.0.1:8765'
    assert command[command.index('--workers') + 1] == '4'
    assert existing.read_text() == 'Preserved'
    for updates in ({'PNBP_WORKERS': '5'}, {'JWT_SECRET': 'REPLACE_' + 'x' * 32},
                    {'PNBP_DATA_DIR': '/other'}, {'PNBP_DATABASE_URL': 'sqlite:///other'},
                    {'PNBP_ASSET_MODE': 'auto'}, {'PNBP_PORT': '80'}):
        with pytest.raises(ValueError):
            startup.command({**environment, **updates}, uid=os.getuid(), state=state)
    with pytest.raises(ValueError, match='non-root'):
        startup.command(environment, uid=0, state=state)
    state.chmod(0o755)
    with pytest.raises(ValueError, match='private'):
        startup.command(environment, uid=os.getuid(), state=state)
