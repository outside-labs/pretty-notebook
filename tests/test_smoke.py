from cli_runner import CliRunner

from pretty_notebook import Notebook
from pretty_notebook.cli import app, cli


def test_registered_command_help() -> None:
	runner = CliRunner()

	root_result = runner.invoke(cli, ["--help"])
	assert root_result.exit_code == 0, root_result.output

	for command_name in sorted([p.name for p in app.programs if p.name] + list(app.children)):
		result = runner.invoke(cli, [command_name, "--help"])
		assert result.exit_code == 0, f"{command_name}:\n{result.output}"


def test_notebook_loads_markdown(monkeypatch, tmp_path) -> None:
	(monkeypatch.chdir(tmp_path))
	(monkeypatch.setenv("NOTE_PATH", str(tmp_path)))
	(monkeypatch.setenv("PNBP_SETTINGS", "off"))
	(tmp_path / "example.md").write_text("#public\nHello.\n", encoding="utf-8")

	notebook = Notebook()

	assert tuple(notebook.notes) == ("example",)
	assert notebook.notes["example"].md == "#public\nHello.\n"
	assert not notebook.has_unsaved_notes
