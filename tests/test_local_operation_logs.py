"""Durable local operation receipts never capture private inputs or exceptions."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from stat import S_IMODE

import pytest
from cli_runner import CliRunner
from pretty_notebook import Notebook
from pretty_notebook.cli import cli
from pretty_notebook._internal import operation_logs as logs
from pretty_notebook.commands.logs import operation_logs


def test_read_is_bounded_and_does_not_create_state(tmp_path):
    assert logs.read(tmp_path) == []
    assert not (tmp_path / '.pnbp').exists()
    for kwargs in ({'limit': 0}, {'limit': 101}, {'before': -1}, {'before': True}):
        with pytest.raises(ValueError):
            logs.read(tmp_path, **kwargs)
    with pytest.raises(ValueError):
        logs.start(tmp_path, 'secret note name')


def test_success_failure_interruption_order_pagination_and_permissions(tmp_path):
    with logs.operation(tmp_path, 'collect'):
        pass
    with pytest.raises(RuntimeError):
        with logs.operation(tmp_path, 'flush'):
            raise RuntimeError('private text and secret bearer token must never be stored')
    interrupted = logs.start(tmp_path, 'publish')
    rows = logs.read(tmp_path)
    assert [row['outcome'] for row in rows] == ['started', 'failed', 'succeeded']
    assert rows[0]['operation_id'] == interrupted
    assert len({row['operation_id'] for row in rows}) == 3
    assert 'private text' not in str(rows) and 'bearer' not in str(rows)
    assert logs.read(tmp_path, limit=1, before=rows[0]['id']) == rows[1:2]
    assert S_IMODE((tmp_path / '.pnbp/operations.sqlite3').stat().st_mode) == 0o600
    assert S_IMODE((tmp_path / '.pnbp').stat().st_mode) == 0o700


def test_retention_caps_history_and_removes_old_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, 'MAX_EVENTS', 3)
    for _ in range(5):
        with logs.operation(tmp_path, 'publish'):
            pass
    rows = logs.read(tmp_path)
    assert len(rows) == 3 and rows[0]['id'] == 5
    with closing(sqlite3.connect(tmp_path / '.pnbp/operations.sqlite3')) as connection:
        connection.execute('UPDATE operation_events SET started_at=?', [(datetime.now(UTC) - timedelta(days=31)).isoformat()])
        connection.commit()
    logs.start(tmp_path, 'collect')
    assert len(logs.read(tmp_path)) == 1


def test_symlinks_nonfiles_and_finalization_failures_fail_safely(tmp_path, monkeypatch, caplog):
    target = tmp_path / 'outside'
    target.mkdir()
    (tmp_path / '.pnbp').symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        logs.start(tmp_path, 'publish')
    (tmp_path / '.pnbp').unlink()
    (tmp_path / '.pnbp').mkdir()
    path = tmp_path / '.pnbp/operations.sqlite3'
    path.symlink_to(target / 'log')
    with pytest.raises(ValueError):
        logs.read(tmp_path)
    path.unlink()
    path.mkdir()
    with pytest.raises(ValueError):
        logs.start(tmp_path, 'publish')
    path.rmdir()
    def fail(*args):
        raise OSError('private filesystem details')
    monkeypatch.setattr(logs, 'finish', fail)
    with logs.operation(tmp_path, 'publish'):
        pass
    with pytest.raises(RuntimeError, match='original'):
        with logs.operation(tmp_path, 'flush'):
            raise RuntimeError('original')
    assert all(row['outcome'] == 'started' for row in logs.read(tmp_path))
    assert 'private filesystem details' not in caplog.text


def test_notebook_flush_publication_and_cli_collect_are_recorded(tmp_path, monkeypatch):
    (tmp_path / 'private-name.md').write_text('Private source contents')
    nb = Notebook(tmp_path, settings_file='off')
    assert nb.save_all_notes() == []
    assert not (tmp_path / '.pnbp').exists()
    nb.notes['private-name'].md_out = 'Private replacement contents'
    nb.save_all_notes()
    assert logs.read(tmp_path)[0]['operation'] == 'flush'
    from pretty_notebook._internal import publishing
    def failed_publish(*args, **kwargs):
        raise RuntimeError('secret connection error')
    monkeypatch.setattr(publishing, 'post_commits', failed_publish)
    with pytest.raises(RuntimeError):
        nb.post_commits_to_web_api()
    assert logs.read(tmp_path)[0]['outcome'] == 'failed'
    before = len(logs.read(tmp_path))
    with pytest.raises(RuntimeError):
        nb.post_commits_to_web_api(stage_only=True)
    assert len(logs.read(tmp_path)) == before
    result = CliRunner().invoke(cli, ['--notebook', str(tmp_path), 'collect-all-stats'])
    assert result.exit_code == 0, result.output
    assert logs.read(tmp_path)[0]['operation'] == 'collect'
    result = CliRunner().invoke(cli, ['--notebook', str(tmp_path), 'logs', '--limit', '2'])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 2
    assert 'Private source' not in result.output and 'private-name' not in result.output
    assert operation_logs(Notebook(tmp_path, settings_file='off'), limit=1) == logs.read(tmp_path, limit=1)
    assert CliRunner().invoke(cli, ['--notebook', str(tmp_path), 'logs', '--limit', '101']).exit_code != 0


def test_compatibility_client_and_remote_response_contract(tmp_path, monkeypatch):
    import pnbp.commands.logs as compatibility
    import pretty_notebook.commands.logs as canonical
    assert compatibility is canonical
    nb = Notebook(tmp_path, settings_file='off')
    with pytest.raises(ValueError):
        operation_logs(nb, limit=101)
    class Response:
        def json(self):
            return [{'unexpected': 'secret response text'}]
    monkeypatch.setattr(nb, '_api_request', lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match='Invalid bounded'):
        operation_logs(nb, remote=True)
