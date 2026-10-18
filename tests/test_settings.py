import json
from stat import S_IMODE

import pytest
from cli_runner import CliRunner

from pretty_notebook import Notebook, NotebookSettings, SettingsError
from pretty_notebook.cli import cli
from pretty_notebook.settings import initialize_notebook, load_settings, save_api_token


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
	for key in NotebookSettings().to_dict().keys() | {"NOTE_PATH", "PNBP_PROFILE", "PNBP_SETTINGS", "API_TOKEN"}:
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv("PNBP_PROFILES", str(tmp_path / "local" / "profiles.json"))


def write_json(path, data):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data), encoding="utf-8")


def test_explicit_path_and_legacy_environment_load_identically(monkeypatch, tmp_path):
	(tmp_path / "entry.md").write_text("#public\nHello!\n", encoding="utf-8")
	write_json(tmp_path / "pnbp_settings.json", {"TITLE": "Notebook", "API_TOKEN": "private", "IMG_PATH": "imgs"})
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	legacy = Notebook()
	explicit = Notebook.open(tmp_path)
	assert explicit.config == legacy.config
	assert explicit.settings == legacy.settings
	assert explicit.API_TOKEN == legacy.API_TOKEN == "private"
	assert explicit.IMG_PATH == str(tmp_path / "imgs")
	assert explicit.notes["entry"].md == legacy.notes["entry"].md
	assert "API_TOKEN" not in explicit.config
	assert not (tmp_path / ".pnbp").exists()


def test_precedence_and_defaults(monkeypatch, tmp_path):
	write_json(tmp_path / ".pnbp" / "settings.json", {"TITLE": "file", "NOTE_NESTED": "recurs", "API_BASE": "https://file.example"})
	monkeypatch.setenv("TITLE", "environment")
	monkeypatch.setenv("API_BASE", "https://env.example")
	monkeypatch.setenv("NOTE_PATH", "/does/not/exist")
	nb = Notebook(tmp_path, settings={"TITLE": "explicit"})
	assert nb.settings.title == "explicit"
	assert nb.API_BASE == "https://env.example"
	assert nb.settings.note_nested == "recurs"
	assert nb.EXCLUDE_TAG == "#private"
	assert nb.NOTE_PATH == str(tmp_path)
	assert Notebook(tmp_path).settings.title == "environment"
	monkeypatch.delenv("TITLE")
	assert Notebook(tmp_path).settings.title == "file"


def test_typed_settings_override_environment(monkeypatch, tmp_path):
	monkeypatch.setenv("NOTE_NESTED", "all")
	nb = Notebook(tmp_path, NotebookSettings(note_nested="single", title="Typed"))
	assert nb.settings.note_nested == "single"
	assert nb.config["TITLE"] == "Typed"


def test_instance_open_still_protects_pending_edits(tmp_path):
	(tmp_path / "example.md").write_text("Original")
	nb = Notebook.open(tmp_path)
	nb.notes["example"].md_out = "Pending"
	with pytest.raises(RuntimeError, match="unsaved"):
		nb.open()
	assert nb.notes["example"].current_md == "Pending"
	nb.open(discard_unsaved=True)
	assert nb.notes["example"].current_md == "Original"


@pytest.mark.parametrize("config", [
	{"NOTE_NESTED": "recursive"}, {"PUB_LNK_ONLY": "false"}, {"darkmode": 1},
	{"IMG_PATH": []}, {"API_BASE": "javascript:private-value"},
	{"API_BASE": "https://user:private-value@example.com"}, {"NAV_PAGES": []},
	{"NAV_PAGES": {"broken": [42]}}, {"TITLE": 3}, {"COMMIT_TAG": "public"},
	{"EXCLUDE_TAG": "#two tags"}, {"API_TOKEN": "private-value"},
	{"extension": {"password": "private-value"}},
])
def test_invalid_settings_fail_without_echoing_values(tmp_path, config):
	with pytest.raises(SettingsError) as error:
		Notebook(tmp_path, settings=config)
	assert "private-value" not in str(error.value)
	assert list(tmp_path.iterdir()) == []


def test_environment_booleans_and_invalid_modes(monkeypatch, tmp_path):
	monkeypatch.setenv("PUB_LNK_ONLY", "false")
	monkeypatch.setenv("darkmode", "1")
	assert Notebook(tmp_path).settings.darkmode is True
	assert Notebook(tmp_path).PUB_LNK_ONLY is False
	monkeypatch.setenv("NOTE_NESTED", "invalid")
	with pytest.raises(SettingsError, match="NOTE_NESTED"):
		Notebook(tmp_path)


def test_settings_off_skips_all_file_state_but_accepts_explicit_settings(monkeypatch, tmp_path):
	write_json(tmp_path / "pnbp_settings.json", {"API_TOKEN": "legacy-secret"})
	write_json(tmp_path / ".pnbp" / "settings.json", {"TITLE": "file"})
	(tmp_path / ".pnbp" / "secrets.json").write_text("not JSON")
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	nb = Notebook(tmp_path, settings={"TITLE": "explicit"})
	assert nb.settings.title == "explicit"
	assert nb.API_TOKEN is None
	assert nb.settings_file is False
	assert nb.credentials_file is None


def test_ambiguous_files_require_selection(monkeypatch, tmp_path):
	write_json(tmp_path / "pnbp_settings.json", {"TITLE": "legacy"})
	write_json(tmp_path / ".pnbp" / "settings.json", {"TITLE": "modern"})
	with pytest.raises(SettingsError, match="Both settings"):
		Notebook(tmp_path)
	assert Notebook(tmp_path, settings_file="pnbp_settings.json").settings.title == "legacy"
	monkeypatch.setenv("PNBP_SETTINGS", ".pnbp/settings.json")
	assert Notebook(tmp_path).settings.title == "modern"
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	assert Notebook(tmp_path, settings_file=".pnbp/settings.json").settings.title == "modern"
	with pytest.raises(SettingsError, match="Both settings"):
		initialize_notebook(tmp_path, migrate=True)


@pytest.mark.parametrize("mode", ["flat", "single", "recurs", "all"])
def test_state_directory_is_never_discovered(tmp_path, mode):
	(tmp_path / "root.md").write_text("Root")
	state = tmp_path / ".pnbp"
	state.mkdir()
	(state / "private.md").write_text("Private")
	(state / "nested").mkdir()
	(state / "nested" / "private.md").write_text("Nested private")
	assert set(Notebook(tmp_path, settings={"NOTE_NESTED": mode}).notes) == {"root"}


def test_migration_preview_and_repeatable_apply(tmp_path, capsys):
	legacy = tmp_path / "pnbp_settings.json"
	write_json(legacy, {"TITLE": "Old", "API_TOKEN": "sensitive-token", "NOTE_NESTED": "recurs", "custom": {"keep": 1}})
	original = legacy.read_bytes()
	before = Notebook(tmp_path)
	preview = initialize_notebook(tmp_path, migrate=True, dry_run=True)
	assert preview.action == "migrate"
	assert not (tmp_path / ".pnbp").exists()
	assert legacy.read_bytes() == original
	result = CliRunner().invoke(cli, ["init", str(tmp_path), "--migrate"])
	assert result.exit_code == 0, result.output
	assert "sensitive-token" not in result.output + capsys.readouterr().out
	after = Notebook(tmp_path)
	assert after.settings == before.settings
	assert after.API_TOKEN == before.API_TOKEN
	assert not legacy.exists()
	assert (tmp_path / ".pnbp" / "legacy-settings.json").read_bytes() == original
	portable = json.loads((tmp_path / ".pnbp" / "settings.json").read_text())
	assert "API_TOKEN" not in portable
	assert portable["custom"] == {"keep": 1}
	assert S_IMODE((tmp_path / ".pnbp" / "secrets.json").stat().st_mode) == 0o600
	assert S_IMODE((tmp_path / ".pnbp" / "legacy-settings.json").stat().st_mode) == 0o600
	assert initialize_notebook(tmp_path, migrate=True).action == "unchanged"


def test_failed_migration_preserves_original_and_can_retry(monkeypatch, tmp_path):
	write_json(tmp_path / "pnbp_settings.json", {"API_TOKEN": "original-token", "TITLE": "Original"})
	original = (tmp_path / "pnbp_settings.json").read_bytes()
	import pretty_notebook.settings as settings_module
	real_write = settings_module._write_exclusive
	def fail_backup(path, content):
		if path.name == "legacy-settings.json":
			raise OSError("simulated failure")
		return real_write(path, content)
	monkeypatch.setattr(settings_module, "_write_exclusive", fail_backup)
	with pytest.raises(OSError, match="simulated"):
		initialize_notebook(tmp_path, migrate=True)
	assert (tmp_path / "pnbp_settings.json").read_bytes() == original
	assert list((tmp_path / ".pnbp").iterdir()) == []
	monkeypatch.setattr(settings_module, "_write_exclusive", real_write)
	assert initialize_notebook(tmp_path, migrate=True).action == "migrate"


def test_external_settings_change_aborts_migration(monkeypatch, tmp_path):
	legacy = tmp_path / "pnbp_settings.json"
	write_json(legacy, {"TITLE": "Original"})
	import pretty_notebook.settings as settings_module
	real_write = settings_module._write_exclusive
	def edit_during_write(path, content):
		real_write(path, content)
		if path.name == "settings.json":
			write_json(legacy, {"TITLE": "External"})
	monkeypatch.setattr(settings_module, "_write_exclusive", edit_during_write)
	with pytest.raises(SettingsError, match="changed during"):
		initialize_notebook(tmp_path, migrate=True)
	assert json.loads(legacy.read_text()) == {"TITLE": "External"}
	assert list((tmp_path / ".pnbp").iterdir()) == []


def test_racing_initialization_never_overwrites_existing_settings(monkeypatch, tmp_path):
	write_json(tmp_path / "pnbp_settings.json", {"API_TOKEN": "legacy-token"})
	import pretty_notebook.settings as settings_module
	real_write = settings_module._write_exclusive
	def create_during_write(path, content):
		if path.name == "settings.json":
			write_json(path, {"TITLE": "Created elsewhere"})
		return real_write(path, content)
	monkeypatch.setattr(settings_module, "_write_exclusive", create_during_write)
	with pytest.raises(FileExistsError):
		initialize_notebook(tmp_path, migrate=True)
	assert (tmp_path / "pnbp_settings.json").exists()
	assert not (tmp_path / ".pnbp" / "secrets.json").exists()
	assert json.loads((tmp_path / ".pnbp" / "settings.json").read_text()) == {"TITLE": "Created elsewhere"}


def test_init_and_profile_preview_do_not_create_directories(monkeypatch, tmp_path):
	root = tmp_path / "new-notebook"
	result = CliRunner().invoke(cli, ["init", str(root), "--profile", "work", "--dry-run"])
	assert result.exit_code == 0, result.output
	assert json.loads(result.output)["dry_run"] is True
	assert not root.exists()
	assert not (tmp_path / "local").exists()


def test_named_profiles_are_local_and_refuse_rebinding(monkeypatch, tmp_path):
	root = tmp_path / "notes"
	initialize_notebook(root, profile="work")
	(root / "example.md").write_text("A note")
	monkeypatch.setenv("NOTE_PATH", "/does/not/exist")
	assert "example" in Notebook.open(profile="work").notes
	monkeypatch.delenv("NOTE_PATH")
	monkeypatch.setenv("PNBP_PROFILE", "work")
	assert Notebook().NOTE_PATH == str(root)
	assert initialize_notebook(root, profile="work").action == "unchanged"
	with pytest.raises(SettingsError, match="another notebook"):
		initialize_notebook(tmp_path / "other", profile="work")
	assert not (tmp_path / "other").exists()
	with pytest.raises(SettingsError, match="Unknown"):
		Notebook(profile="missing")


def test_secret_priority_and_redacted_loaded_repr(monkeypatch, tmp_path):
	write_json(tmp_path / "pnbp_settings.json", {"API_TOKEN": "legacy-token"})
	save_api_token(tmp_path / ".pnbp" / "secrets.json", "stored-token")
	assert Notebook(tmp_path).API_TOKEN == "stored-token"
	monkeypatch.setenv("API_TOKEN", "environment-token")
	assert Notebook(tmp_path).API_TOKEN == "environment-token"
	loaded = load_settings(tmp_path, api_token="explicit-token")
	assert loaded.api_token == "explicit-token"
	assert "explicit-token" not in repr(loaded)
	assert "API_TOKEN" not in loaded.config


def test_failed_secret_replacement_preserves_previous_token(monkeypatch, tmp_path):
	secret = tmp_path / ".pnbp" / "secrets.json"
	save_api_token(secret, "previous")
	def fail_replace(*args):
		raise OSError("simulated replacement failure")
	monkeypatch.setattr("pnbp.settings.os.replace", fail_replace)
	with pytest.raises(OSError, match="simulated"):
		save_api_token(secret, "new-token")
	assert json.loads(secret.read_text())["API_TOKEN"] == "previous"
	assert list(secret.parent.iterdir()) == [secret]


def test_empty_legacy_token_is_preserved_by_migration(tmp_path):
	write_json(tmp_path / "pnbp_settings.json", {"API_TOKEN": ""})
	initialize_notebook(tmp_path, migrate=True)
	assert Notebook(tmp_path).API_TOKEN == ""


def test_read_only_settings_remain_usable(tmp_path):
	write_json(tmp_path / ".pnbp" / "settings.json", {"TITLE": "Read only"})
	(tmp_path / ".pnbp" / "settings.json").chmod(0o400)
	assert Notebook(tmp_path).settings.title == "Read only"


def test_navigation_labels_are_not_credential_fields(tmp_path):
	nb = Notebook(tmp_path, settings={"NAV_PAGES": {"API tokens": "/tokens", "password": "/docs"}})
	assert nb.settings.nav_pages["API tokens"] == "/tokens"


def test_symlinked_state_is_rejected_for_writes(tmp_path):
	root, elsewhere = tmp_path / "notes", tmp_path / "elsewhere"
	root.mkdir()
	elsewhere.mkdir()
	(root / ".pnbp").symlink_to(elsewhere, target_is_directory=True)
	with pytest.raises(SettingsError, match="symlinked"):
		initialize_notebook(root)
	with pytest.raises(SettingsError, match="symlinked"):
		save_api_token(root / ".pnbp" / "secrets.json", "token")
	assert list(elsewhere.iterdir()) == []


def test_invalid_json_is_reported_without_source_text(tmp_path):
	write_json(tmp_path / ".pnbp" / "settings.json", {})
	(tmp_path / ".pnbp" / "settings.json").write_text('{"API_TOKEN": "private-broken')
	with pytest.raises(SettingsError, match="Invalid JSON") as error:
		Notebook(tmp_path)
	assert "private-broken" not in str(error.value)


def test_missing_path_is_not_initialized(tmp_path):
	with pytest.raises(FileNotFoundError):
		Notebook.open(tmp_path / "missing")
	assert not (tmp_path / "missing").exists()
