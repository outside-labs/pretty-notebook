from contextlib import closing
from pretty_notebook._internal.web_state import CURRENT_VERSION
import json
from pathlib import Path
import sqlite3

import pytest
from cli_runner import CliRunner
from pretty_notebook.cli import cli
from pretty_notebook._internal.web_state import inspect_web_state
from pretty_notebook.settings import initialize_notebook
from web_state_fixture import create_state


def test_notebook_doctor_is_bounded_read_only_and_redacted(tmp_path, monkeypatch):
    root = tmp_path / 'notes'
    root.mkdir()
    (root / 'private.md').write_text('Synthetic note text must stay private')
    monkeypatch.setenv('API_TOKEN', 'synthetic-secret-do-not-print')
    monkeypatch.setenv('PNBP_SETTINGS', 'off')
    initialize_notebook(root)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob('*') if path.is_file()}
    result = CliRunner().invoke(cli, ['--notebook', str(root), 'doctor', '--json'])
    assert result.exit_code == 0, result.exception
    report = json.loads(result.output)
    assert report['ok'] and len(report['checks']) < 20
    assert 'synthetic-secret-do-not-print' not in result.output and 'Synthetic note text' not in result.output
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob('*') if path.is_file()} == before


def test_doctor_configuration_failure_is_structured_and_does_not_echo_exception(monkeypatch):
    def fail(**kwargs):
        raise ValueError('synthetic-secret-from-invalid-input')
    monkeypatch.setattr('pretty_notebook.models.Notebook', fail)
    result = CliRunner().invoke(cli, ['doctor', '--json'])
    assert result.exit_code == 1
    assert not json.loads(result.output)['ok']
    assert 'synthetic-secret-from-invalid-input' not in result.output


def test_server_diagnostics_inspect_schema_blobs_and_counts(tmp_path):
    state = create_state(tmp_path / 'state')
    before = {path: path.read_bytes() for path in state.rglob('*') if path.is_file()}
    report = inspect_web_state(state)
    assert report == {'state': 'ok', 'schema_version': CURRENT_VERSION, 'migration_needed': False,
                      'retained_blobs': 1, 'users': 1, 'inbox_messages': 1}
    assert before == {path: path.read_bytes() for path in state.rglob('*') if path.is_file()}
    blob, = (state / 'pages/.blobs').iterdir()
    blob.write_text('Corruption')
    with pytest.raises(ValueError, match='blob'):
        inspect_web_state(state)


@pytest.mark.parametrize('sql', [
    'DELETE FROM pnbp_schema_migrations WHERE version=1',
    "UPDATE pnbp_schema_migrations SET name='unknown' WHERE version=2",
    'UPDATE pnbp_schema_migrations SET version=100 WHERE version=2',
    'DROP TABLE user',
    'UPDATE pnbp_notes SET current_revision=2',
])
def test_server_diagnostics_reject_inconsistent_state(tmp_path, sql):
    state = create_state(tmp_path / 'state')
    with closing(sqlite3.connect(state / 'db.sqlite3')) as connection:
        connection.execute(sql)
        connection.commit()
    with pytest.raises(ValueError):
        inspect_web_state(state)


def test_missing_and_future_database_do_not_initialize_files(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert inspect_web_state(empty, allow_new=True)['state'] == 'new'
    assert not list(empty.iterdir())
    with pytest.raises(ValueError, match='database'):
        inspect_web_state(empty)
    (empty / 'db.sqlite3').write_bytes(b'not a database')
    with pytest.raises(ValueError, match='verified'):
        inspect_web_state(empty)
