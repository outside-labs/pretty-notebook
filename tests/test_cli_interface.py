"""Regression coverage for the installed command boundary and invocation state."""

import json
from pathlib import Path
import subprocess

import pytest

from cli_runner import CliRunner
from pretty_notebook._internal.cli_tools import edit_text
from pretty_notebook.cli import app, cli


@pytest.mark.parametrize("arguments", [
    ["--unknown"], ["search", "term", "--limit", "0"],
    ["search", "term", "--limit", "201"], ["search", "term", "--offset", "-1"],
    ["search", "term", "--field", "unknown"], ["search", "term", "--lim", "2"],
    ["note", "show"], ["deploy", "plan", "--revision", "a" * 40],
])
def test_invalid_inputs_exit_two_without_loading_notebook(monkeypatch, arguments):
    monkeypatch.setattr("pretty_notebook.cli.Notebook", lambda **kwargs: pytest.fail("opened a notebook"))
    result = CliRunner().invoke(cli, arguments)
    assert result.exit_code == 2, (result.output, result.exception)
    assert "error" in result.output.lower()


def test_nested_help_never_executes_setup(monkeypatch):
    monkeypatch.setattr(app, "setup", lambda: pytest.fail("executed setup"))
    for arguments in (["--help"], ["note", "edit", "--help"], ["deploy", "check", "--help"]):
        result = CliRunner().invoke(cli, arguments)
        assert result.exit_code == 0, (result.output, result.exception)


def test_repeated_invocations_have_independent_notebook_state(monkeypatch, tmp_path):
    monkeypatch.setenv("PNBP_SETTINGS", "off")
    runner = CliRunner()
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        (root / (name + ".md")).write_text("Hello", encoding="utf-8")
        result = runner.invoke(cli, ["--notebook", str(root), "status", "--json"])
        assert result.exit_code == 0, result.exception
        assert Path(json.loads(result.output)["path"]) == root


def test_file_input_and_stdin_edits(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTE_PATH", str(tmp_path))
    monkeypatch.setenv("PNBP_SETTINGS", "off")
    source = tmp_path / "input.txt"
    source.write_text("café\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["note", "add", "example", "--file", str(source)])
    assert result.exit_code == 0, result.exception
    assert (tmp_path / "example.md").read_text(encoding="utf-8") == "café\n"
    result = runner.invoke(cli, ["note", "edit", "example", "--file", "-"], input="Changed\n")
    assert result.exit_code == 0, result.exception
    assert (tmp_path / "example.md").read_text(encoding="utf-8") == "Changed\n"


def test_editor_uses_argument_vector_and_detects_unchanged_text(monkeypatch):
    monkeypatch.setenv("VISUAL", 'editor --wait "two words"')
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs == {"check": True}
        assert Path(command[-1]).stat().st_mode & 0o077 == 0

    monkeypatch.setattr(subprocess, "run", run)
    assert edit_text("Original\n") is None
    assert calls[0][:-1] == ["editor", "--wait", "two words"]

    def changed(command, **kwargs):
        Path(command[-1]).write_text("", encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", changed)
    assert edit_text("Original\n") == ""
