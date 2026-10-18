import subprocess

from expose_interface import CommandError
import pytest

from pretty_notebook import Notebook
from pretty_notebook.commands import commit as commit_commands


def _git(path, *args, check=True):
	return subprocess.run(
		["git", "-C", str(path), *args],
		check=check,
		capture_output=True,
		text=True,
	)


def _init_repo(path):
	path.mkdir(parents=True, exist_ok=True)
	_git(path, "init", "--quiet")
	_git(path, "config", "user.name", "Pretty Notebook Tests")
	_git(path, "config", "user.email", "tests@example.invalid")


def _load_notebook(monkeypatch, path):
	monkeypatch.setenv("NOTE_PATH", str(path))
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	return Notebook()


def _staged_paths(path):
	result = _git(path, "diff", "--cached", "--name-only", "-z")
	return tuple(item for item in result.stdout.split("\0") if item)


def test_nested_parent_repository_requires_explicit_root(monkeypatch, tmp_path):
	repository = tmp_path / "project"
	notes = repository / "notes"
	_init_repo(repository)
	notes.mkdir()
	(notes / "entry.md").write_text("hello\n", encoding="utf-8")
	(repository / "sibling.txt").write_text("do not stage\n", encoding="utf-8")
	notebook = _load_notebook(monkeypatch, notes)

	with pytest.raises(CommandError, match="repository root"):
		commit_commands._git_commit_notebook(nb=notebook)

	assert _staged_paths(repository) == ()


def test_explicit_parent_repository_commits_only_notebook(monkeypatch, tmp_path):
	repository = tmp_path / "project"
	notes = repository / "notes"
	_init_repo(repository)
	notes.mkdir()
	(notes / "entry.md").write_text("hello\n", encoding="utf-8")
	(repository / "sibling.txt").write_text("do not stage\n", encoding="utf-8")
	notebook = _load_notebook(monkeypatch, notes)

	commit_commands._git_commit_notebook(repo_root=repository, nb=notebook)

	committed = _git(
		repository,
		"show",
		"--pretty=format:",
		"--name-only",
		"HEAD",
	).stdout.splitlines()
	assert committed == ["notes/entry.md"]
	assert _staged_paths(repository) == ()
	assert "?? sibling.txt" in _git(repository, "status", "--short").stdout


def test_existing_staged_change_aborts_before_notebook_add(monkeypatch, tmp_path):
	repository = tmp_path / "project"
	notes = repository / "notes"
	_init_repo(repository)
	notes.mkdir()
	(notes / "entry.md").write_text("hello\n", encoding="utf-8")
	(repository / "sibling.txt").write_text("already staged\n", encoding="utf-8")
	_git(repository, "add", "sibling.txt")
	notebook = _load_notebook(monkeypatch, notes)

	with pytest.raises(CommandError, match="staged changes"):
		commit_commands._git_commit_notebook(repo_root=repository, nb=notebook)

	assert _staged_paths(repository) == ("sibling.txt",)
	assert _git(repository, "rev-parse", "--verify", "HEAD", check=False).returncode != 0


def test_private_settings_excluded_but_docs_example_committed(monkeypatch, tmp_path):
	_init_repo(tmp_path)
	(tmp_path / "entry.md").write_text("hello\n", encoding="utf-8")
	(tmp_path / "pnbp_settings.json").write_text('{"API_TOKEN": "private"}\n', encoding="utf-8")
	(tmp_path / "docs").mkdir()
	(tmp_path / "docs" / "pnbp_settings.json").write_text("{}\n", encoding="utf-8")
	notebook = _load_notebook(monkeypatch, tmp_path)

	commit_commands._init_git_ignore(path=tmp_path)
	commit_commands._git_commit_notebook(nb=notebook)

	tracked = set(_git(tmp_path, "ls-files").stdout.splitlines())
	assert tracked == {".gitignore", "docs/pnbp_settings.json", "entry.md"}
	assert _git(tmp_path, "check-ignore", "pnbp_settings.json").returncode == 0
	assert _git(tmp_path, "check-ignore", "docs/pnbp_settings.json", check=False).returncode == 1


def test_commit_excludes_settings_without_gitignore_setup(monkeypatch, tmp_path):
	_init_repo(tmp_path)
	(tmp_path / "entry.md").write_text("hello\n", encoding="utf-8")
	(tmp_path / "pnbp_settings.json").write_text('{"API_TOKEN": "private"}\n', encoding="utf-8")
	notebook = _load_notebook(monkeypatch, tmp_path)

	commit_commands._git_commit_notebook(nb=notebook)

	assert _git(tmp_path, "ls-files").stdout.splitlines() == ["entry.md"]
	assert "?? pnbp_settings.json" in _git(tmp_path, "status", "--short").stdout


@pytest.mark.parametrize("nested", [False, True])
def test_new_credentials_and_migration_backup_never_staged(monkeypatch, tmp_path, nested):
	_init_repo(tmp_path)
	root = tmp_path / "notes" if nested else tmp_path
	root.mkdir(exist_ok=True)
	(root / "entry.md").write_text("hello\n")
	(root / ".pnbp").mkdir()
	for name in ("secrets.json", "legacy-settings.json"):
		(root / ".pnbp" / name).write_text('{"API_TOKEN": "private"}\n')
	(root / ".pnbp" / ".secrets-writing.tmp").write_text('{"API_TOKEN": "private"}\n')
	(root / ".pnbp" / "drafts").mkdir()
	(root / ".pnbp" / "drafts" / "edit.md").write_text("Private unsaved draft")
	(root / ".pnbp" / "metadata.lock").write_text("")
	(root / ".pnbp" / ".metadata-writing.tmp").write_text("Partial state")
	(root / ".pnbp" / "operations" / "private").mkdir(parents=True)
	(root / ".pnbp" / "operations" / "private" / "original.md").write_text("Private original source")
	(root / ".pnbp-change-writing.tmp").write_text("Partial note source")
	(root / ".pnbp" / "settings.json").write_text('{"TITLE": "Portable"}\n')
	notebook = _load_notebook(monkeypatch, root)
	commit_commands._git_commit_notebook(repo_root=tmp_path if nested else None, nb=notebook)
	prefix = "notes/" if nested else ""
	assert set(_git(tmp_path, "ls-files").stdout.splitlines()) == {
		prefix + "entry.md", prefix + ".pnbp/settings.json",
	}
	assert _staged_paths(tmp_path) == ()


def test_commit_records_tracked_deletions(monkeypatch, tmp_path):
	_init_repo(tmp_path)
	(tmp_path / "old.md").write_text("Original")
	notebook = _load_notebook(monkeypatch, tmp_path)
	commit_commands._git_commit_notebook(nb=notebook)
	(tmp_path / "old.md").unlink()
	commit_commands._git_commit_notebook(nb=notebook)
	assert _git(tmp_path, "ls-files").stdout == ""


def test_failed_commit_leaves_notebook_changes_unstaged(monkeypatch, tmp_path):
	_init_repo(tmp_path)
	(tmp_path / "entry.md").write_text("hello\n", encoding="utf-8")
	notebook = _load_notebook(monkeypatch, tmp_path)
	original_run_git = commit_commands._run_git

	def fail_commit(repository, *args, **kwargs):
		if args and args[0] == "commit":
			raise CommandError("simulated commit failure")
		return original_run_git(repository, *args, **kwargs)

	monkeypatch.setattr(commit_commands, "_run_git", fail_commit)

	with pytest.raises(CommandError, match="simulated commit failure"):
		commit_commands._git_commit_notebook(nb=notebook)

	assert _staged_paths(tmp_path) == ()
	assert "?? entry.md" in _git(tmp_path, "status", "--short").stdout


def test_gitignore_setup_preserves_rules_and_is_idempotent(tmp_path):
	gitignore = tmp_path / ".gitignore"
	gitignore.write_text("custom.log\n", encoding="utf-8")

	commit_commands._init_git_ignore(path=tmp_path)
	commit_commands._init_git_ignore(path=tmp_path)

	lines = gitignore.read_text(encoding="utf-8").splitlines()
	assert lines[0] == "custom.log"
	assert lines.count("custom.log") == 1
	assert lines.count("/pnbp_settings.json") == 1
