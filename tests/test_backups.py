from contextlib import closing
from dataclasses import replace
from importlib.metadata import version
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess

import pytest

from cli_runner import CliRunner
from pretty_notebook.cli import cli
from pretty_notebook._internal import backups
from pretty_notebook._internal.deployment import DeploySpec, bundle
from web_state_fixture import create_state

REQUIRE_STOPPED = backups._require_stopped


def git(checkout, *arguments):
    return subprocess.run(['git', '-C', str(checkout), *arguments], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def site(tmp_path, monkeypatch):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    fixture_version = version('pretty-notebook')
    (checkout / 'pyproject.toml').write_text(f'[project]\nversion="{fixture_version}"\n')
    git(checkout, 'init', '-q')
    git(checkout, 'add', 'pyproject.toml')
    git(checkout, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'Synthetic fixture')
    state = create_state(tmp_path / 'state')
    spec = DeploySpec(git(checkout, 'rev-parse', 'HEAD'), 'notes.example.com', checkout=checkout,
                      data_dir=state, env_file=tmp_path / 'environment', backup_dir=tmp_path / 'backups',
                      user=pwd.getpwuid(os.getuid()).pw_name)
    spec.env_file.write_text(bundle(spec)['environment.example'].replace('REPLACE_WITH_A_PRIVATE_RANDOM_SECRET', 's' * 32).replace('REPLACE_WITH_A_DIFFERENT_PRIVATE_RANDOM_SECRET', 'b' * 32))
    spec.env_file.chmod(0o600)
    monkeypatch.setattr(backups, '_require_stopped', lambda *args, **kwargs: None)
    return spec


def test_preview_and_private_round_trip_preserve_complete_state(site, tmp_path):
    output = tmp_path / 'checkpoint'
    assert backups.backup_site(site, output)['apply'] is False
    assert not output.exists()
    report = backups.backup_site(site, output, apply=True)
    assert report['verified']
    receipt = backups.verify_backup(output)
    assert receipt['code']['revision'] == site.revision
    assert receipt['inventory']['files']['state/images/fixture.png']
    for path in [output, *output.rglob('*')]:
        assert path.stat().st_mode & 0o077 == 0
    restored = tmp_path / 'restored'
    assert backups.restore_site(site, output, restored)['apply'] is False
    assert not restored.exists()
    result = backups.restore_site(site, output, restored, apply=True)
    assert result['verified'] and result['activation_required']
    state = restored / 'state'
    assert (state / 'images/fixture.png').read_bytes() == (site.data_dir / 'images/fixture.png').read_bytes()
    assert (state / 'web-settings.json').read_bytes() == (site.data_dir / 'web-settings.json').read_bytes()
    assert (restored / 'environment.original').read_bytes() == site.env_file.read_bytes()
    assert f'PNBP_DATA_DIR={state}' in (restored / 'environment').read_text()
    with closing(sqlite3.connect(state / 'db.sqlite3')) as connection:
        assert connection.execute('SELECT tok_uuid FROM user').fetchone()[0] == 'synthetic-revocation-uuid'
        assert 'Synthetic message' in connection.execute('SELECT payload FROM formsubmission').fetchone()[0]
    assert (site.data_dir / 'db.sqlite3').exists() and (output / 'manifest.json').exists()
    with pytest.raises(ValueError, match='new output'):
        backups.restore_site(site, output, restored, apply=True)


@pytest.mark.parametrize('damage', ['missing', 'modified', 'extra', 'incomplete', 'symlink', 'version'])
def test_corrupt_or_incomplete_backups_refuse_restore(site, tmp_path, damage):
    output = tmp_path / 'checkpoint'
    backups.backup_site(site, output, apply=True)
    image = output / 'state/images/fixture.png'
    if damage == 'missing': image.unlink()
    elif damage == 'modified': image.write_bytes(b'corrupt')
    elif damage == 'extra': (output / 'unexpected').write_text('extra')
    elif damage == 'incomplete': (output / '.incomplete').write_text('interrupted')
    elif damage == 'symlink':
        image.unlink()
        image.symlink_to(site.data_dir / 'images/fixture.png')
    elif damage == 'version':
        manifest = json.loads((output / 'manifest.json').read_text())
        manifest['code']['revision'] = 'f' * 40
        (output / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises((ValueError, OSError)):
        backups.restore_site(site, output, tmp_path / 'restored', apply=True)
    assert not (tmp_path / 'restored').exists()


def test_changed_sources_leave_unusable_checkpoint_and_original_intact(site, tmp_path, monkeypatch):
    original = backups._snapshot_database
    def changed(source, target):
        original(source, target)
        (site.data_dir / 'images/fixture.png').write_bytes(b'external change')
    monkeypatch.setattr(backups, '_snapshot_database', changed)
    output = tmp_path / 'checkpoint'
    with pytest.raises(ValueError, match='Source changed'):
        backups.backup_site(site, output, apply=True)
    assert (output / '.incomplete').exists() and not (output / 'manifest.json').exists()
    assert (site.data_dir / 'images/fixture.png').read_bytes() == b'external change'
    with pytest.raises(ValueError, match='incomplete'):
        backups.verify_backup(output)


def test_backup_refuses_symlinks_existing_outputs_and_overlapping_locations(site, tmp_path):
    output = tmp_path / 'checkpoint'
    output.mkdir()
    with pytest.raises(ValueError, match='new output'):
        backups.backup_site(site, output, apply=True)
    with pytest.raises(ValueError, match='separate'):
        backups.backup_site(site, site.data_dir / 'backup', apply=True)
    (site.data_dir / 'images/link').symlink_to(site.env_file)
    with pytest.raises(ValueError, match='regular'):
        backups.backup_site(site, tmp_path / 'linked', apply=True)
    assert not (tmp_path / 'linked').exists()


def test_committed_wal_is_included_in_consistent_database_snapshot(site, tmp_path):
    with closing(sqlite3.connect(site.data_dir / 'db.sqlite3')) as connection:
        assert connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        connection.execute("UPDATE user SET tok_uuid='wal-revocation-state'")
        connection.commit()
        output = tmp_path / 'checkpoint'
        backups.backup_site(site, output, apply=True)
        with closing(sqlite3.connect(output / 'state/db.sqlite3')) as restored:
            assert restored.execute('SELECT tok_uuid FROM user').fetchone()[0] == 'wal-revocation-state'
        assert not (output / 'state/db.sqlite3-wal').exists()


@pytest.mark.parametrize('fields,accepted', [
    ('LoadState=loaded\nActiveState=inactive\nMainPID=0', True),
    ('LoadState=loaded\nActiveState=active\nMainPID=123', False),
    ('LoadState=not-found\nActiveState=inactive\nMainPID=0', False),
    ('LoadState=loaded\nActiveState=deactivating\nMainPID=0', False),
])
def test_service_state_requires_independent_stopped_evidence(site, monkeypatch, fields, accepted):
    implementation = REQUIRE_STOPPED
    monkeypatch.setattr(backups, '_run_checked', lambda *args, **kwargs: fields)
    if accepted:
        implementation(site, 'vps', {})
    else:
        with pytest.raises(ValueError, match='Stop'):
            implementation(site, 'vps', {})


def test_revision_mismatch_and_cli_preview(site, tmp_path):
    with pytest.raises(ValueError, match='matching'):
        backups.backup_site(replace(site, revision='f' * 40), tmp_path / 'wrong')
    arguments = ['deploy', 'backup', '--output', str(tmp_path / 'preview')]
    for key, value in site.to_dict().items():
        arguments += ['--' + key.replace('_', '-'), str(value)]
    result = CliRunner().invoke(cli, arguments)
    assert result.exit_code == 0, result.exception
    assert not json.loads(result.output)['apply']
    assert not (tmp_path / 'preview').exists()
    assert 's' * 32 not in result.output and 'b' * 32 not in result.output


def test_active_source_lock_refuses_backup(site, tmp_path):
    import fcntl
    with (site.data_dir / 'site.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='operation is running'):
            backups.backup_site(site, tmp_path / 'locked', apply=True)
    assert not (tmp_path / 'locked').exists()


@pytest.mark.parametrize('state', [
    {'Status': 'running', 'Running': True, 'Pid': 123},
    {'Status': 'restarting', 'Running': False, 'Restarting': True, 'Pid': 0},
    {'Status': 'exited', 'Running': False, 'Pid': 0},
])
def test_container_stop_check_and_image_match(site, monkeypatch, state):
    def checked(arguments, **kwargs):
        return json.dumps(state) if '{{json .State}}' in arguments else 'sha256:fixture'
    monkeypatch.setattr(backups, '_run_checked', checked)
    if state['Status'] == 'exited':
        REQUIRE_STOPPED(site, 'container', {'image_id': 'sha256:fixture'})
        with pytest.raises(ValueError, match='matching'):
            REQUIRE_STOPPED(site, 'container', {'image_id': 'sha256:different'})
    else:
        with pytest.raises(ValueError, match='matching'):
            REQUIRE_STOPPED(site, 'container', {'image_id': 'sha256:fixture'})


def test_interrupted_restoration_never_marks_output_ready(site, tmp_path, monkeypatch):
    checkpoint = tmp_path / 'checkpoint'
    backups.backup_site(site, checkpoint, apply=True)
    original = backups._scan
    def changed(root, **kwargs):
        result = original(root, **kwargs)
        if kwargs.get('copy_to') is not None:
            (checkpoint / 'state/images/fixture.png').write_bytes(b'changed during restore')
        return result
    monkeypatch.setattr(backups, '_scan', changed)
    restored = tmp_path / 'restored'
    with pytest.raises(ValueError, match='corrupt'):
        backups.restore_site(site, checkpoint, restored, apply=True)
    assert (restored / '.incomplete').exists() and not (restored / 'restore.json').exists()
    assert (site.data_dir / 'images/fixture.png').read_bytes() == b'synthetic-image'


@pytest.mark.skipif(os.geteuid() == 0, reason='Root can read directories without permission bits')
def test_unreadable_subdirectory_cannot_be_silently_omitted(site, tmp_path):
    private = site.data_dir / 'extra-private-state'
    private.mkdir(mode=0o700)
    (private / 'record').write_text('Preserve this state')
    private.chmod(0)
    output = tmp_path / 'checkpoint'
    try:
        with pytest.raises(PermissionError):
            backups.backup_site(site, output, apply=True)
        assert not output.exists()
    finally:
        private.chmod(0o700)
