import json
from stat import S_IMODE

from cli_runner import CliRunner

import pretty_notebook.cli as cli_module
from pretty_notebook import Notebook
from pretty_notebook.cli import cli


def test_settings_off_ignores_existing_settings_file(monkeypatch, tmp_path):
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	(tmp_path / "pnbp_settings.json").write_text(
		json.dumps(
			{
				"API_BASE": "https://remote.example",
				"API_TOKEN": "should-not-load",
				"TITLE": "Configured title",
			}
		),
		encoding="utf-8",
	)

	nb = Notebook()

	assert nb.settings_file is False
	assert nb.API_BASE is None
	assert nb.API_TOKEN is None
	assert "TITLE" not in nb.config


def test_missing_settings_never_prompt_or_write(monkeypatch, tmp_path, capsys):
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	monkeypatch.delenv("PNBP_SETTINGS", raising=False)
	def unexpected_prompt(*args):
		raise AssertionError("Construction must not prompt")
	monkeypatch.setattr("builtins.input", unexpected_prompt)

	nb = Notebook()

	assert nb.settings_file is False
	assert list(tmp_path.iterdir()) == []
	assert capsys.readouterr().out == ""


def test_init_generates_portable_settings_explicitly(monkeypatch, tmp_path):
	monkeypatch.delenv("PNBP_SETTINGS", raising=False)
	result = CliRunner().invoke(cli, ["init", str(tmp_path)])
	generated = json.loads((tmp_path / ".pnbp" / "settings.json").read_text())

	assert result.exit_code == 0, result.output
	assert "TITLE" in generated
	assert "API_TOKEN" not in generated
	assert Notebook(tmp_path).config["TITLE"] == ""
	assert not (tmp_path / ".git").exists()


def test_commit_settings_uses_remote_by_default_and_local_only_when_requested(monkeypatch):
	targets = []

	class FakeNotebook:
		def __init__(self):
			self.API_BASE = "https://remote.example"

		def web_settings_post(self):
			targets.append(self.API_BASE)

	monkeypatch.setattr(cli_module, "Notebook", FakeNotebook)
	runner = CliRunner()

	remote = runner.invoke(cli, ["commit-settings"])
	local = runner.invoke(cli, ["commit-settings", "--local"])

	assert remote.exit_code == 0, remote.output
	assert local.exit_code == 0, local.output
	assert targets == ["https://remote.example", "http://127.0.0.1:8000"]


def test_refresh_token_redacts_token_output(monkeypatch, tmp_path, capsys):
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	monkeypatch.delenv("PNBP_SETTINGS", raising=False)
	settings = {
		"API_BASE": "https://remote.example",
		"API_TOKEN": "old-token",
	}
	(tmp_path / "pnbp_settings.json").write_text(json.dumps(settings), encoding="utf-8")
	nb = Notebook()

	class Response:
		status_code = 200
		text = '{"access_token":"new-secret-token","token_type":"bearer"}'

		def json(self):
			return {"access_token": "new-secret-token", "token_type": "bearer"}

		def __str__(self):
			return "<Response [200]>"

	captured = {}

	def post(*args, **kwargs):
		captured.update(kwargs)
		return Response()

	monkeypatch.setattr("builtins.input", lambda prompt="": "ella")
	monkeypatch.setattr("getpass.getpass", lambda prompt="": "password")
	monkeypatch.setattr("pnbp.models.notebook.requests.post", post)

	nb.refresh_token()
	output = capsys.readouterr().out

	assert "new-secret-token" not in output
	assert "old-token" not in output
	assert "<redacted>" in output
	assert nb.API_TOKEN == "new-secret-token"
	assert "authorization" not in captured["headers"]
	assert captured["timeout"] == nb.REQUEST_TIMEOUT
	persisted = json.loads((tmp_path / ".pnbp" / "secrets.json").read_text(encoding="utf-8"))
	assert persisted["API_TOKEN"] == "new-secret-token"
	assert S_IMODE((tmp_path / ".pnbp" / "secrets.json").stat().st_mode) == 0o600
	assert json.loads((tmp_path / "pnbp_settings.json").read_text()) == settings
	assert Notebook().API_TOKEN == "new-secret-token"


def test_initial_user_creation_sends_bootstrap_secret_without_bearer_none(
	monkeypatch,
	tmp_path,
):
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	nb = Notebook()
	nb.API_BASE = "https://notes.example"
	captured = {}

	class Response:
		status_code = 200

		def json(self):
			return {"id": 1, "username": "ella"}

		def __str__(self):
			return "<Response [200]>"

	passwords = iter(["correct horse battery staple", "correct horse battery staple"])
	monkeypatch.setattr("getpass.getpass", lambda _message="": next(passwords))

	def post(url, **kwargs):
		captured.update({"url": url, **kwargs})
		return Response()

	monkeypatch.setattr("pnbp.models.notebook.requests.post", post)

	nb.create_api_user(username="ella", bootstrap_token="bootstrap-secret")

	assert captured["headers"]["X-PNBP-Bootstrap-Token"] == "bootstrap-secret"
	assert "authorization" not in captured["headers"]
	assert captured["timeout"] == nb.REQUEST_TIMEOUT
