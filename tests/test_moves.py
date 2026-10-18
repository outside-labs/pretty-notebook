import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from cli_runner import CliRunner

from pretty_notebook import Notebook, IdentityError
from pretty_notebook._internal import identities as _identities, journal as _journal, moves as _moves
from pretty_notebook.cli import cli


@pytest.fixture
def notebook(tmp_path, monkeypatch):
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	monkeypatch.delenv("NOTE_PATH", raising=False)
	(tmp_path / "nested").mkdir()
	(tmp_path / "nested" / "Original.md").write_bytes(b"# Intro\r\n\r\n[[./Neighbor|Near]] [[../Root#One|Root]] [[#Intro]]\r\n")
	(tmp_path / "nested" / "Neighbor.md").write_bytes(b"Neighbor\r\n")
	(tmp_path / "Root.md").write_bytes(b"# One\r\n")
	(tmp_path / "Reader.md").write_bytes(b"Original prose\r\n[[ nested/Original # Intro | Keep label ]] [[TheAlias]]\r\n`[[nested/Original]]` ![[nested/Original]]\r\n```text\r\n[[nested/Original]]\r\n```\r\n")
	_identities.initialize_identities(tmp_path)
	index = _identities.load_index(tmp_path)
	notes = tuple(replace(note, title="Display title", aliases=("TheAlias",), route="custom/route") if note.path == "nested/Original.md" else note for note in index.notes)
	with _identities.identity_operation(tmp_path) as expected:
		_identities._write_index(tmp_path, replace(index, notes=notes), expected)
	return Notebook(tmp_path, settings={"NOTE_NESTED": "all"})


def _snapshot(root):
	return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file() and (path.suffix.lower() == ".md" or path.name == "metadata.json")}


def _assert_moved(nb, original_id):
	root = Path(nb.NOTE_PATH)
	index = _identities.load_index(root)
	assert index.by_path()["elsewhere/Renamed.md"].id == original_id
	assert index.by_path()["elsewhere/Renamed.md"].title == "Display title"
	assert index.by_path()["elsewhere/Renamed.md"].route == "custom/route"
	assert index.by_path()["elsewhere/Renamed.md"].aliases == ("TheAlias", "Original")
	assert (root / "elsewhere" / "Renamed.md").read_bytes() == b"# Intro\r\n\r\n[[../nested/Neighbor|Near]] [[../Root#One|Root]] [[#Intro]]\r\n"
	assert (root / "Reader.md").read_bytes() == b"Original prose\r\n[[ elsewhere/Renamed # Intro | Keep label ]] [[elsewhere/Renamed]]\r\n`[[nested/Original]]` ![[nested/Original]]\r\n```text\r\n[[nested/Original]]\r\n```\r\n"
	assert not (root / "nested" / "Original.md").exists()
	assert not nb.graph_index().diagnostics()


def test_move_dry_run_has_exact_changes_and_writes_nothing(notebook):
	before = _snapshot(Path(notebook.NOTE_PATH))
	paths = sorted(path.relative_to(Path(notebook.NOTE_PATH)).as_posix() for path in Path(notebook.NOTE_PATH).rglob("*"))
	plan = notebook.move_note("nested/Original", "elsewhere/Renamed", dry_run=True)
	assert plan["note_id"] == notebook.notes["nested/Original"].note_id
	assert plan["changed_files"] == ["nested/Original.md", "elsewhere/Renamed.md", "Reader.md", ".pnbp/metadata.json"]
	assert len(plan["replacements"]) == 3
	assert plan["url_aliases"] == [{"from": "/nested-original", "to": "/elsewhere-renamed"}]
	assert plan["operation_id"] is None
	assert _snapshot(Path(notebook.NOTE_PATH)) == before
	assert sorted(path.relative_to(Path(notebook.NOTE_PATH)).as_posix() for path in Path(notebook.NOTE_PATH).rglob("*")) == paths


def test_move_preserves_source_bytes_identity_metadata_and_permissions(notebook):
	original = notebook.notes["nested/Original"].note_id
	(Path(notebook.NOTE_PATH) / "nested" / "Original.md").chmod(0o640)
	plan = notebook.move_note(notebook.notes["nested/Original"], "elsewhere/Renamed")
	_assert_moved(notebook, original)
	assert stat.S_IMODE((Path(notebook.NOTE_PATH) / "elsewhere" / "Renamed.md").stat().st_mode) == 0o640
	assert notebook.move_operations()[0]["state"] == "committed"
	assert plan["operation_id"] == notebook.move_operations()[0]["id"]
	assert not (Path(notebook.NOTE_PATH) / ".pnbp" / "metadata.lock").exists()


@pytest.mark.parametrize("action", ["resume", "rollback"])
@pytest.mark.parametrize("failed_path", ["nested/Original.md", "elsewhere/Renamed.md", "Reader.md", ".pnbp/metadata.json"])
def test_restart_recovers_failure_after_each_write(notebook, monkeypatch, action, failed_path):
	before = _snapshot(Path(notebook.NOTE_PATH))
	original = notebook.notes["nested/Original"].note_id
	real_write = _journal._write
	def interrupted(root, change, old, new):
		real_write(root, change, old, new)
		if change["path"] == failed_path:
			raise OSError("simulated interruption after file commit")
	monkeypatch.setattr(_journal, "_write", interrupted)
	with pytest.raises(_journal.JournalError, match="interrupted"):
		notebook.move_note("nested/Original", "elsewhere/Renamed")
	operation, = notebook.move_operations()
	assert operation["state"] == "failed"
	monkeypatch.setattr(_journal, "_write", real_write)
	restarted = Notebook(Path(notebook.NOTE_PATH), settings={"NOTE_NESTED": "all"})
	preview = restarted.recover_move(operation["id"], action=action, dry_run=True)
	assert preview["dry_run"] is True
	assert restarted.move_operations()[0]["state"] == "failed"
	result = restarted.recover_move(operation["id"], action=action)
	if action == "resume":
		assert result["state"] == "committed"
		_assert_moved(restarted, original)
	else:
		assert result["state"] == "rolled_back"
		assert _snapshot(Path(notebook.NOTE_PATH)) == before
	assert not (Path(notebook.NOTE_PATH) / ".pnbp" / "metadata.lock").exists()
	assert list(Path(notebook.NOTE_PATH).rglob(".pnbp-change-*.tmp")) == []


def test_external_backlink_edit_before_apply_is_preserved_and_rollback_skips_it(notebook, monkeypatch):
	before = _snapshot(Path(notebook.NOTE_PATH))
	real_prepare = _journal.prepare
	def externally_edited(root, changes, **kwargs):
		operation = real_prepare(root, changes, **kwargs)
		(root / "Reader.md").write_bytes(b"External editor owns this text\r\n")
		return operation
	monkeypatch.setattr(_journal, "prepare", externally_edited)
	with pytest.raises(_journal.JournalError, match="External edit"):
		notebook.move_note("nested/Original", "elsewhere/Renamed")
	assert (Path(notebook.NOTE_PATH) / "nested" / "Original.md").read_bytes() == before["nested/Original.md"]
	assert not (Path(notebook.NOTE_PATH) / "elsewhere").exists()
	operation, = notebook.move_operations()
	with pytest.raises(IdentityError, match="Unfinished operation"):
		notebook.generate_note("New", "Pending")
	with pytest.raises(_journal.JournalError, match="Unfinished operation"):
		notebook._publication_preflight()
	assert not (Path(notebook.NOTE_PATH) / "New.md").exists()
	notebook.recover_move(operation["id"], action="rollback")
	assert (Path(notebook.NOTE_PATH) / "Reader.md").read_bytes() == b"External editor owns this text\r\n"
	assert (Path(notebook.NOTE_PATH) / ".pnbp" / "metadata.json").read_bytes() == before[".pnbp/metadata.json"]


def test_external_edit_after_completed_write_blocks_recovery_without_overwrite(notebook, monkeypatch):
	real_write = _journal._write
	def interrupted(root, change, old, new):
		real_write(root, change, old, new)
		if change["path"] == "Reader.md":
			raise OSError("interrupted")
	monkeypatch.setattr(_journal, "_write", interrupted)
	with pytest.raises(_journal.JournalError):
		notebook.move_note("nested/Original", "elsewhere/Renamed")
	monkeypatch.setattr(_journal, "_write", real_write)
	(Path(notebook.NOTE_PATH) / "Reader.md").write_bytes(b"New external version")
	before = _snapshot(Path(notebook.NOTE_PATH))
	operation, = notebook.move_operations()
	for action in ("resume", "rollback"):
		with pytest.raises(_journal.JournalError, match="External edit"):
			notebook.recover_move(operation["id"], action=action)
		assert _snapshot(Path(notebook.NOTE_PATH)) == before


def test_case_only_rename_and_rollback_use_exact_directory_spellings(notebook):
	old_id = notebook.notes["nested/Original"].note_id
	before = _snapshot(Path(notebook.NOTE_PATH))
	plan = notebook.rename_note("nested/Original", "original.md")
	assert "original.md" in {path.name for path in (Path(notebook.NOTE_PATH) / "nested").iterdir()}
	assert "Original.md" not in {path.name for path in (Path(notebook.NOTE_PATH) / "nested").iterdir()}
	assert notebook.notes["nested/original"].note_id == old_id
	assert "[[ nested/original # Intro | Keep label ]]" in (Path(notebook.NOTE_PATH) / "Reader.md").read_text()
	notebook.recover_move(plan["operation_id"], action="rollback")
	assert _snapshot(Path(notebook.NOTE_PATH)) == before


def test_ambiguous_basename_is_reported_and_not_rewritten(notebook):
	root = Path(notebook.NOTE_PATH)
	(root / "left").mkdir()
	(root / "right").mkdir()
	(root / "left" / "same.md").write_text("Left")
	(root / "right" / "same.md").write_text("Right")
	(root / "ambiguous.md").write_text("[[same]] [[left/same]]")
	notebook.initialize_identities()
	plan = notebook.move_note("left/same", "left/new")
	assert (root / "ambiguous.md").read_text() == "[[same]] [[left/new]]"
	assert any(item["state"] == "ambiguous" for item in plan["diagnostics"])
	with pytest.raises(ValueError, match="ambiguous"):
		# Add another same basename to keep the source ambiguous after the move.
		(root / "left" / "same.md").write_text("Left again")
		notebook.initialize_identities()
		notebook.move_note("same", "elsewhere/other")


@pytest.mark.parametrize("destination", ["../escape", ".pnbp/draft", "/absolute", "nested/Neighbor", "nested/neighbor"])
def test_invalid_or_colliding_destination_does_not_modify_notes(notebook, destination):
	before = _snapshot(Path(notebook.NOTE_PATH))
	with pytest.raises((ValueError, FileExistsError)):
		notebook.move_note("nested/Original", destination)
	assert _snapshot(Path(notebook.NOTE_PATH)) == before
	assert not notebook.move_operations()


def test_pending_edits_and_uninitialized_identities_are_explicit_boundaries(notebook, tmp_path):
	notebook.notes["Root"].md_out = "Pending"
	with pytest.raises(ValueError, match="pending edits"):
		notebook.rename_note("nested/Original", "New")
	assert notebook.notes["Root"].md_out == "Pending"
	plain = tmp_path / "plain"
	plain.mkdir()
	(plain / "one.md").write_text("Text")
	with pytest.raises(IdentityError, match="pnbp init"):
		Notebook(plain).rename_note("one", "two", dry_run=True)
	assert not (plain / ".pnbp").exists()


def test_cli_move_preview_apply_operations_and_rollback(notebook):
	runner = CliRunner()
	base = ["--notebook", str(Path(notebook.NOTE_PATH)), "note"]
	preview = runner.invoke(cli, [*base, "move", "nested/Original", "elsewhere/Renamed", "--dry-run"])
	assert preview.exit_code == 0, preview.output
	assert json.loads(preview.output)["dry_run"]
	assert not notebook.move_operations()
	applied = runner.invoke(cli, [*base, "move", "nested/Original", "elsewhere/Renamed"])
	assert applied.exit_code == 0, applied.output
	id = json.loads(applied.output)["operation_id"]
	listed = runner.invoke(cli, [*base, "operations"])
	assert json.loads(listed.output)["operations"][0]["id"] == id
	rolled_back = runner.invoke(cli, [*base, "recover", id, "--action", "rollback"])
	assert rolled_back.exit_code == 0, rolled_back.output
	assert json.loads(rolled_back.output)["state"] == "rolled_back"


def test_recovery_rejects_corrupt_backup_and_symlinked_destinations(notebook):
	outside = Path(notebook.NOTE_PATH) / "outside"
	outside.mkdir()
	(Path(notebook.NOTE_PATH) / "symlink").symlink_to(outside, target_is_directory=True)
	with pytest.raises(_journal.JournalError, match="regular directories"):
		notebook.move_note("nested/Original", "symlink/Note")
	plan = notebook.move_note("nested/Original", "elsewhere/Renamed")
	operation = Path(notebook.NOTE_PATH) / ".pnbp" / "operations" / plan["operation_id"]
	(operation / "before" / "0000").write_bytes(b"corrupted backup")
	before = _snapshot(Path(notebook.NOTE_PATH))
	with pytest.raises(_journal.JournalError, match="checksum mismatch"):
		notebook.recover_move(plan["operation_id"], action="rollback")
	assert _snapshot(Path(notebook.NOTE_PATH)) == before


def test_process_exit_before_progress_record_is_recoverable(notebook, monkeypatch):
	real_write = _journal._write
	def exit_process(root, change, old, new):
		real_write(root, change, old, new)
		if change["path"] == "elsewhere/Renamed.md":
			raise SystemExit("simulated abrupt process exit")
	monkeypatch.setattr(_journal, "_write", exit_process)
	with pytest.raises(SystemExit):
		notebook.move_note("nested/Original", "elsewhere/Renamed")
	operation, = notebook.move_operations()
	assert operation["state"] == "applying"
	monkeypatch.setattr(_journal, "_write", real_write)
	restarted = Notebook(notebook.NOTE_PATH, settings={"NOTE_NESTED": "all"})
	restarted.recover_move(operation["id"])
	_assert_moved(restarted, notebook.notes["nested/Original"].note_id)


def test_changed_source_snapshot_stops_before_preparing_journal(notebook, monkeypatch):
	real_files = _moves._files
	calls = 0
	def changed_on_revalidation(root):
		nonlocal calls
		calls += 1
		if calls == 2:
			(root / "Reader.md").write_bytes(b"External changes before journaling")
		return real_files(root)
	monkeypatch.setattr(_moves, "_files", changed_on_revalidation)
	with pytest.raises(_journal.JournalError, match="before the move"):
		notebook.move_note("nested/Original", "elsewhere/Renamed")
	assert not notebook.move_operations()
	assert (Path(notebook.NOTE_PATH) / "nested" / "Original.md").exists()
	assert not (Path(notebook.NOTE_PATH) / "elsewhere").exists()


def test_identical_external_destination_is_not_adopted_as_an_applied_step(notebook, monkeypatch):
	real_prepare = _journal.prepare
	def external_copy(root, changes, **kwargs):
		operation = real_prepare(root, changes, **kwargs)
		(root / "elsewhere").mkdir()
		(root / "elsewhere" / "Renamed.md").write_bytes(changes[1].after)
		return operation
	monkeypatch.setattr(_journal, "prepare", external_copy)
	with pytest.raises(_journal.JournalError, match="External edit"):
		notebook.move_note("nested/Original", "elsewhere/Renamed")
	operation, = notebook.move_operations()
	notebook.recover_move(operation["id"], action="rollback")
	assert (Path(notebook.NOTE_PATH) / "nested" / "Original.md").exists()
	assert (Path(notebook.NOTE_PATH) / "elsewhere" / "Renamed.md").exists()


def test_interrupted_rollback_can_be_restarted(notebook, monkeypatch):
	before = _snapshot(Path(notebook.NOTE_PATH))
	plan = notebook.move_note("nested/Original", "elsewhere/Renamed")
	real_write = _journal._write
	def interrupted(root, change, old, new):
		real_write(root, change, old, new)
		if change["path"] == "Reader.md":
			raise OSError("interrupted rollback")
	monkeypatch.setattr(_journal, "_write", interrupted)
	with pytest.raises(_journal.JournalError, match="interrupted"):
		notebook.recover_move(plan["operation_id"], action="rollback")
	monkeypatch.setattr(_journal, "_write", real_write)
	restarted = Notebook(notebook.NOTE_PATH, settings={"NOTE_NESTED": "all"})
	restarted.recover_move(plan["operation_id"], action="rollback")
	assert _snapshot(Path(notebook.NOTE_PATH)) == before


def test_failed_atomic_backlink_replace_keeps_original_and_cleans_temp(notebook, monkeypatch):
	before = _snapshot(Path(notebook.NOTE_PATH))
	real_replace = _journal.os.replace
	def fail_backlink(source, destination):
		if str(source).split("/")[-1].startswith(".pnbp-change-") and str(destination).endswith("/Reader.md"):
			raise OSError("cannot replace backlink")
		return real_replace(source, destination)
	monkeypatch.setattr(_journal.os, "replace", fail_backlink)
	with pytest.raises(_journal.JournalError, match="cannot replace backlink"):
		notebook.move_note("nested/Original", "elsewhere/Renamed")
	assert (Path(notebook.NOTE_PATH) / "Reader.md").read_bytes() == before["Reader.md"]
	assert list(Path(notebook.NOTE_PATH).rglob(".pnbp-change-*.tmp")) == []
	monkeypatch.setattr(_journal.os, "replace", real_replace)
	operation, = notebook.move_operations()
	notebook.recover_move(operation["id"], action="rollback")
	assert _snapshot(Path(notebook.NOTE_PATH)) == before
