import json
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from cli_runner import CliRunner

from pretty_notebook import Notebook, IdentityError
from pretty_notebook.cli import cli
from pretty_notebook._internal import identities as _identities


@pytest.fixture
def root(monkeypatch, tmp_path):
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	monkeypatch.delenv("NOTE_NESTED", raising=False)
	monkeypatch.delenv("NOTE_PATH", raising=False)
	(tmp_path / "first.md").write_bytes(b"Identical source\r\n")
	(tmp_path / "nested").mkdir()
	(tmp_path / "nested" / "second.MD").write_bytes(b"Identical source\r\n")
	return tmp_path


def test_discovery_is_read_only_and_missing_index_has_diagnostic(root):
	nb = Notebook(root)
	assert nb.notebook_id is None
	assert nb.notes["first"].note_id is None
	assert nb.identity_status()["state"] == "missing"
	assert not (root / ".pnbp").exists()


def test_explicit_init_assigns_distinct_ids_and_restart_preserves_them(root):
	preview = CliRunner().invoke(cli, ["init", str(root), "--dry-run"])
	assert preview.exit_code == 0, preview.output
	assert not (root / ".pnbp").exists()
	result = CliRunner().invoke(cli, ["init", str(root)])
	assert result.exit_code == 0, result.output
	index = _identities.load_index(root)
	assert len(index.notes) == 2
	assert len({note.id for note in index.notes}) == 2
	assert index.notes[0].source_hash == index.notes[1].source_hash
	assert str(UUID(index.notebook_id)) == index.notebook_id
	nb = Notebook(root, settings={"NOTE_NESTED": "recurs"})
	assert nb.notebook_id == index.notebook_id
	assert {note.note_id for note in nb.notes.values()} == {note.id for note in index.notes}
	assert json.loads(result.output)["identities"]["action"] == "initialize"
	before = (root / ".pnbp" / "metadata.json").read_bytes()
	assert _identities.initialize_identities(root)["action"] == "unchanged"
	assert (root / ".pnbp" / "metadata.json").read_bytes() == before


def test_explicit_copy_gets_new_identity_even_when_content_matches(root):
	_identities.initialize_identities(root)
	before = _identities.load_index(root)
	shutil.copyfile(root / "first.md", root / "copied.md")
	nb = Notebook(root)
	assert nb.notes["copied"].note_id is None
	assert nb.identity_status()["unindexed"] == ["copied.md"]
	nb.initialize_identities()
	after = _identities.load_index(root)
	assert after.notebook_id == before.notebook_id
	assert after.by_path()["first.md"].id == before.by_path()["first.md"].id
	assert after.by_path()["copied.md"].id not in {note.id for note in before.notes}


def test_save_and_creation_persist_ids_without_replacing_existing_identity(root):
	_identities.initialize_identities(root)
	nb = Notebook(root)
	note = nb.notes["first"]
	original = note.note_id
	note.md_out = "Changed source"
	saved = note.save(nb)
	assert saved.note_id == original
	created = nb.generate_note("third", "Identical source\r\n")
	assert created.note_id is not None and created.note_id != original
	restarted = Notebook(root)
	assert restarted.notes["first"].note_id == original
	assert restarted.notes["third"].note_id == created.note_id


def test_clone_preserves_ids_and_explicit_fork_retains_backup(root, tmp_path):
	_identities.initialize_identities(root)
	clone = root.parent / f"{root.name}-clone"
	shutil.copytree(root, clone)
	try:
		old = _identities.load_index(root)
		nb = Notebook(clone)
		assert nb.notebook_id == old.notebook_id
		original = (clone / ".pnbp" / "metadata.json").read_bytes()
		preview = nb.fork_identities(dry_run=True)
		assert preview["dry_run"] is True
		assert (clone / ".pnbp" / "metadata.json").read_bytes() == original
		applied = nb.fork_identities()
		new = _identities.load_index(clone)
		assert nb.notebook_id == new.notebook_id != old.notebook_id
		assert not {note.id for note in old.notes} & {note.id for note in new.notes}
		assert Path(applied["backup"]).read_bytes() == original
		assert _identities.load_index(root) == old
	finally:
		shutil.rmtree(clone)


def test_duplicate_ids_and_corrupt_metadata_leave_markdown_readable(root):
	_identities.initialize_identities(root)
	path = root / ".pnbp" / "metadata.json"
	data = json.loads(path.read_text())
	data["notes"][1]["id"] = data["notes"][0]["id"]
	path.write_text(json.dumps(data))
	nb = Notebook(root)
	assert nb.notes["first"].current_md == "Identical source\n"
	assert nb.identity_status()["state"] == "invalid"
	assert "Duplicate" in nb.identity_error
	with pytest.raises(IdentityError, match="Duplicate"):
		nb.initialize_identities()
	path.write_text("broken JSON")
	assert Notebook(root).identity_status()["state"] == "invalid"


@pytest.mark.parametrize("field,value", [("version", True), ("version", 2), ("API_TOKEN", "private-value")])
def test_invalid_schema_is_recoverable_and_does_not_echo_values(root, field, value):
	_identities.initialize_identities(root)
	path = root / ".pnbp" / "metadata.json"
	data = json.loads(path.read_text())
	data[field] = value
	path.write_text(json.dumps(data))
	nb = Notebook(root)
	assert nb.identity_status()["state"] == "invalid"
	assert "private-value" not in nb.identity_error


def test_ambiguous_external_rename_is_reported_and_never_auto_reconciled(root):
	_identities.initialize_identities(root)
	original = _identities.load_index(root).by_path()["first.md"].id
	(root / "first.md").rename(root / "renamed.md")
	shutil.copyfile(root / "renamed.md", root / "other.md")
	status = Notebook(root).identity_status()
	assert status["missing"] == ["first.md"]
	assert status["rename_candidates"][0]["ambiguous"] is True
	assert status["rename_candidates"][0]["candidate_count"] == 2
	with pytest.raises(IdentityError, match="reconcile"):
		_identities.initialize_identities(root)
	before = (root / ".pnbp" / "metadata.json").read_bytes()
	_identities.reconcile_identity(root, "first.md", "renamed.md", dry_run=True)
	assert (root / ".pnbp" / "metadata.json").read_bytes() == before
	_identities.reconcile_identity(root, "first.md", "renamed.md")
	_identities.initialize_identities(root)
	index = _identities.load_index(root)
	assert index.by_path()["renamed.md"].id == original
	assert index.by_path()["other.md"].id != original


def test_case_only_external_rename_preserves_id_through_reconciliation(root):
	_identities.initialize_identities(root)
	original = _identities.load_index(root).by_path()["first.md"].id
	(root / "first.md").rename(root / "First.md")
	_identities.reconcile_identity(root, "first.md", "First.md")
	assert Notebook(root).notes["First"].note_id == original


def test_unindexed_moves_block_identity_creation_before_writing_note(root):
	_identities.initialize_identities(root)
	(root / "first.md").rename(root / "moved.md")
	nb = Notebook(root)
	with pytest.raises(IdentityError, match="reconciliation"):
		nb.generate_note("new", "New")
	assert not (root / "new.md").exists()


def test_failed_index_replacement_preserves_previous_index_and_lock_is_cleaned(root, monkeypatch):
	_identities.initialize_identities(root)
	path = root / ".pnbp" / "metadata.json"
	original = path.read_bytes()
	def fail_replace(*args):
		raise OSError("simulated identity write failure")
	monkeypatch.setattr("pnbp._identities.os.replace", fail_replace)
	with pytest.raises(OSError, match="simulated"):
		_identities.fork_identities(root)
	assert path.read_bytes() == original
	assert not (root / ".pnbp" / "metadata.lock").exists()
	assert list((root / ".pnbp").glob(".metadata-*.tmp")) == []


def test_metadata_edit_during_save_is_not_overwritten_and_pending_text_survives(root, monkeypatch):
	_identities.initialize_identities(root)
	nb = Notebook(root)
	note = nb.notes["first"]
	note.md_out = "Our pending edit"
	path = root / ".pnbp" / "metadata.json"
	real_write = _identities.record_saved_note
	def edit_index(root, saved, index, expected_bytes):
		data = json.loads(path.read_text())
		data["notes"][0]["title"] = "Externally edited metadata"
		path.write_text(json.dumps(data))
		return real_write(root, saved, index, expected_bytes)
	monkeypatch.setattr(_identities, "record_saved_note", edit_index)
	with pytest.raises(IdentityError, match="changed during"):
		note.save(nb)
	assert note.md_out == "Our pending edit"
	assert nb.notes["first"] is note
	assert json.loads(path.read_text())["notes"][0]["title"] == "Externally edited metadata"
	assert (root / "first.md").read_text() == "Our pending edit"
	assert not (root / ".pnbp" / "metadata.lock").exists()


def test_active_or_interrupted_lock_refuses_writes_but_not_reads(root):
	_identities.initialize_identities(root)
	(root / ".pnbp" / "metadata.lock").write_text("")
	nb = Notebook(root)
	assert nb.notes["first"].note_id is not None
	with pytest.raises(IdentityError, match="in progress or interrupted"):
		nb.fork_identities()


def test_metadata_title_aliases_and_route_survive_fork(root):
	_identities.initialize_identities(root)
	index = _identities.load_index(root)
	note = replace(index.notes[0], title="Café", aliases=("Alias",), route="custom/path")
	updated = replace(index, notes=(note, *index.notes[1:]))
	with _identities.identity_operation(root) as expected:
		_identities._write_index(root, updated, expected)
	nb = Notebook(root)
	assert nb.notes["first"].identity.title == "Café"
	nb.fork_identities()
	assert nb.notes["first"].identity.aliases == ("Alias",)
	assert nb.notes["first"].identity.route == "custom/path"


def test_identity_manifest_export_keeps_ids_and_is_independent(root):
	_identities.initialize_identities(root)
	nb = Notebook(root)
	manifest = nb.export_identities()
	assert _identities.IdentityIndex.from_dict(manifest) == _identities.load_index(root)
	manifest["notes"].clear()
	assert len(nb.export_identities()["notes"]) == 2
	assert "API_TOKEN" not in json.dumps(nb.export_identities())


def test_invalid_index_blocks_cli_init_before_settings_write(root):
	(root / ".pnbp").mkdir()
	(root / ".pnbp" / "metadata.json").write_text("invalid")
	result = CliRunner().invoke(cli, ["init", str(root)])
	assert result.exit_code != 0
	assert "Invalid JSON" in result.output
	assert not (root / ".pnbp" / "settings.json").exists()


def test_case_path_collision_reconciliation_is_refused(root):
	_identities.initialize_identities(root)
	(root / "first.md").rename(root / "moved.md")
	with pytest.raises(IdentityError, match="destination"):
		_identities.reconcile_identity(root, "first.md", "nested/second.MD")


def test_symlinked_index_is_never_replaced(root):
	_identities.initialize_identities(root)
	path = root / ".pnbp" / "metadata.json"
	backup = root / ".pnbp" / "original.json"
	path.rename(backup)
	path.symlink_to(backup)
	original = backup.read_bytes()
	with pytest.raises(IdentityError, match="symlinked"):
		_identities.fork_identities(root)
	assert backup.read_bytes() == original


def test_symlinked_index_blocks_save_before_changing_markdown(root):
	_identities.initialize_identities(root)
	nb = Notebook(root)
	note = nb.notes["first"]
	note.md_out = "Pending content"
	path = root / ".pnbp" / "metadata.json"
	backup = root / ".pnbp" / "original.json"
	path.rename(backup)
	path.symlink_to(backup)
	with pytest.raises(IdentityError, match="symlinked"):
		note.save(nb)
	assert (root / "first.md").read_bytes() == b"Identical source\r\n"
	assert note.md_out == "Pending content"
	assert Notebook(root).identity_status()["state"] == "invalid"
