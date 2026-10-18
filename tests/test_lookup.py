import pytest
from cli_runner import CliRunner

from pretty_notebook import Notebook
from pretty_notebook.cli import cli
from pretty_notebook.helpers import pass_nb
from pretty_notebook.models.components import Link


@pytest.fixture
def notebook(monkeypatch, tmp_path):
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	(tmp_path / "topic.md").write_text("Topic.\n", encoding="utf-8")
	(tmp_path / "topic.md.old.md").write_text("Exact dotted name.\n", encoding="utf-8")
	return Notebook()


def test_exact_dotted_name_resolves_before_extension_normalization(notebook):
	note = notebook.get("topic.md.old")

	assert note is notebook.notes["topic.md.old"]


def test_only_terminal_note_extensions_are_normalized(notebook):
	assert notebook.get("topic.md") is notebook.notes["topic"]
	assert notebook.get("topic.html") is notebook.notes["topic"]
	assert notebook.get("topic.md.old") is notebook.notes["topic.md.old"]


def test_fuzzy_lookup_returns_match_directly_and_can_be_disabled(notebook):
	assert notebook.get("topik") is notebook.notes["topic"]
	assert notebook.get("topik", fuzzy=False) is None


def test_link_lookup_uses_its_note_component(notebook):
	assert notebook.get(Link("topic#section")) is notebook.notes["topic"]
	assert notebook.get(Link("topic|label")) is notebook.notes["topic"]


def test_link_lookup_honors_note_attribute_on_string_subtype(notebook):
	class LinkLike(str):
		note = "topic"

	assert notebook.get(LinkLike("topic#section")) is notebook.notes["topic"]


def test_command_note_resolution_requires_explicit_fuzzy_acceptance(notebook):
	@pass_nb
	def select_note(note=None, nb=None):
		return note

	with pytest.raises(KeyError, match="does not exist"):
		select_note(note="topik", nb=notebook)

	assert select_note(note="topik", fuzzy=True, nb=notebook) is notebook.notes["topic"]


def test_note_commands_advertise_fuzzy_acceptance_flag():
	result = CliRunner().invoke(cli, ["pprint", "--help"])

	assert result.exit_code == 0, result.output
	assert "--fuzzy" in result.output
