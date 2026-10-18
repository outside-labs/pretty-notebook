import json
from datetime import datetime
from stat import S_IMODE

import pytest
from cli_runner import CliRunner

from pretty_notebook import Notebook
from pretty_notebook.cli import app, cli, BUILTIN_COMMANDS
from pretty_notebook.settings import initialize_notebook


@pytest.fixture
def notes(monkeypatch, tmp_path):
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	monkeypatch.delenv("NOTE_NESTED", raising=False)
	monkeypatch.delenv("API_TOKEN", raising=False)
	return tmp_path


def test_add_show_and_explicit_empty_edit(notes):
	runner = CliRunner()
	created = runner.invoke(cli, ["note", "add", "nested/example", "--content", "Unicode café\n"])
	assert created.exit_code == 0, created.output
	shown = runner.invoke(cli, ["note", "show", "nested/example"])
	assert shown.exit_code == 0, shown.output
	assert shown.output == "Unicode café\n"
	empty = runner.invoke(cli, ["note", "edit", "nested/example", "--content", ""])
	assert empty.exit_code == 0, empty.output
	assert (notes / "nested" / "example.md").read_text() == ""


def test_add_never_overwrites_and_accepts_stdin(notes):
	runner = CliRunner()
	result = runner.invoke(cli, ["note", "add", "example", "--file", "-"], input="Original\n")
	assert result.exit_code == 0, result.output
	refused = runner.invoke(cli, ["note", "add", "example", "--content", "Replacement"])
	assert refused.exit_code != 0
	assert (notes / "example.md").read_text() == "Original\n"


def test_note_source_options_are_mutually_exclusive(notes):
	(notes / "source.md").write_text("Source")
	result = CliRunner().invoke(cli, ["note", "add", "new", "--content", "Text", "--file", str(notes / "source.md")])
	assert result.exit_code != 0
	assert not (notes / "new.md").exists()


@pytest.mark.parametrize("name", ["../outside", ".pnbp/private", ".git/config"])
def test_note_commands_reject_unsafe_destinations(notes, name):
	result = CliRunner().invoke(cli, ["note", "add", name, "--content", "Text"])
	assert result.exit_code != 0
	assert list(notes.iterdir()) == []


def test_show_requires_an_exact_note_and_never_writes(notes):
	(notes / "example.md").write_text("Original")
	result = CliRunner().invoke(cli, ["note", "show", "exampl"])
	assert result.exit_code != 0
	assert (notes / "example.md").read_text() == "Original"


def test_editor_cancel_does_not_write(notes, monkeypatch):
	(notes / "example.md").write_text("Original")
	monkeypatch.setattr("pnbp.cli.edit_text", lambda *args, **kwargs: None)
	result = CliRunner().invoke(cli, ["note", "edit", "example"])
	assert result.exit_code == 0, result.output
	assert (notes / "example.md").read_text() == "Original"
	assert not (notes / ".pnbp").exists()


def test_editor_external_change_refuses_save_and_retains_draft(notes, monkeypatch):
	source = notes / "example.MD"
	source.write_text("Original")
	def edit(text, **kwargs):
		assert text == "Original"
		source.write_text("External edit")
		return "Our editor draft\n"
	monkeypatch.setattr("pnbp.cli.edit_text", edit)
	result = CliRunner().invoke(cli, ["note", "edit", "example"])
	assert result.exit_code != 0
	assert "changed on disk" in result.output
	assert "Draft retained at" in result.output
	assert source.read_text() == "External edit"
	drafts = list((notes / ".pnbp" / "drafts").glob("*.md"))
	assert len(drafts) == 1
	assert drafts[0].read_text() == "Our editor draft\n"
	assert S_IMODE(drafts[0].stat().st_mode) == 0o600


def test_profile_selection_reaches_legacy_commands(notes, monkeypatch, tmp_path):
	registry = tmp_path / "profiles.json"
	monkeypatch.setenv("PNBP_PROFILES", str(registry))
	initialize_notebook(notes, profile="work")
	(notes / "example.md").write_text("Selected notebook body")
	monkeypatch.setenv("NOTE_PATH", "/does/not/exist")
	result = CliRunner().invoke(cli, ["--profile", "work", "pprint", "--note", "example"])
	assert result.exit_code == 0, result.output
	assert "Selected notebook body" in result.output
	assert registry.read_text().find("API_TOKEN") == -1


def test_explicit_notebook_path_takes_precedence(notes, monkeypatch):
	(notes / "example.md").write_text("Chosen")
	monkeypatch.setenv("NOTE_PATH", "/does/not/exist")
	result = CliRunner().invoke(cli, ["--notebook", str(notes), "note", "show", "example"])
	assert result.exit_code == 0, result.output
	assert result.output == "Chosen"


def test_default_registration_is_explicit_and_helpers_are_not_commands():
	assert all(func.__name__.startswith("_") for func in BUILTIN_COMMANDS)
	assert len(BUILTIN_COMMANDS) == len(set(BUILTIN_COMMANDS))
	assert not {"run-git", "resolve-repository", "staged-paths", "note-path", "mention-pattern"} & ({p.name for p in app.programs} | set(app.children))


def test_search_and_status_json_are_quiet_bounded_and_redacted(notes, monkeypatch):
	(notes / "b.md").write_text("match private-token")
	(notes / "a.md").write_text("match first")
	monkeypatch.setenv("API_TOKEN", "private-token")
	runner = CliRunner()
	result = runner.invoke(cli, ["search", "match", "--json", "--limit", "1"])
	assert result.exit_code == 0, result.output
	data = json.loads(result.output)
	assert [hit["name"] for hit in data["hits"]] == ["a"]
	second = runner.invoke(cli, ["search", "match", "--json", "--offset", "1"])
	assert "private-token" not in second.output
	assert "<redacted>" in second.output
	status = runner.invoke(cli, ["status", "--json"])
	assert status.exit_code == 0, status.output
	assert json.loads(status.output)["notes"] == 2
	assert "API_TOKEN" not in status.output
	assert set(notes.iterdir()) == {notes / "b.md", notes / "a.md"}


def test_legacy_publication_json_reads_only_and_reports_truncation(notes, monkeypatch):
	import requests
	monkeypatch.setenv("API_BASE", "https://publish.example")
	def legacy_capabilities(self, method, path, **kwargs):
		assert method is requests.get and path == "/api/publishing/capabilities"
		response = requests.Response()
		response.status_code = 404
		response.raise_for_status()
	monkeypatch.setattr(Notebook, "_api_request", legacy_capabilities)
	(notes / "example.md").write_text("#public\nBody")
	reads = []
	def pages(self):
		reads.append("pages")
		return {"unrelated.html": datetime(2000, 1, 1)}
	def images(self):
		reads.append("images")
		return {}
	monkeypatch.setattr(Notebook, "get_pub_commits", pages)
	monkeypatch.setattr(Notebook, "get_img_commits", images)
	def unexpected_write(*args, **kwargs):
		raise AssertionError("Dry-run must not write")
	monkeypatch.setattr("pnbp.models.notebook.requests.post", unexpected_write)
	monkeypatch.setattr("pnbp.models.notebook.requests.delete", unexpected_write)
	before = (notes / "example.md").read_bytes()
	result = CliRunner().invoke(cli, ["commit-stage", "--json", "--limit", "1"])
	assert result.exit_code == 0, result.output
	plan = json.loads(result.output)
	assert plan["mode"] == "legacy-0.9"
	assert plan["dry_run"] is True
	assert plan["pages"] == [{"name": "example.html", "note": "example", "action": "create"}]
	assert plan["page_count"] == 2 and plan["truncated"] is True
	assert reads == ["pages", "images"]
	assert (notes / "example.md").read_bytes() == before
	assert not (notes / ".pnbp").exists()
