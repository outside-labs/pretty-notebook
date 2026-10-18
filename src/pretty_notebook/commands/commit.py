import datetime
import re
import subprocess
from pathlib import Path, PurePosixPath

from expose_interface import CommandError, option

from pretty_notebook.helpers import _convert_datetime, pass_nb

_GITIGNORE_PATTERNS = (
	".DS_Store",
	"**/__pycache__/",
	"*.sqlite3",
	"*.sublime-*",
	"*.pkl",
	"*.py[co]",
	"**/migrations/0*.py",
	"*egg-info/",
	"/pnbp_settings.json",
	"/.pnbp/secrets.json",
	"/.pnbp/legacy-settings.json",
	"/.pnbp/.secrets-*.tmp",
	"/.pnbp/drafts/",
	"/.pnbp/metadata.lock",
	"/.pnbp/.metadata-*.tmp",
	"/.pnbp/operations/",
	"**/.pnbp-change-*.tmp",
	".env",
)


def _run_git(repository, *args, allowed_returncodes=(0,), input=None):
	result = subprocess.run(
		["git", "-C", str(repository), *args],
		check=False,
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		input=input,
	)
	if result.returncode not in allowed_returncodes:
		detail = (result.stderr or result.stdout).strip()
		if not detail:
			detail = f"exit status {result.returncode}"
		raise CommandError(f"Git command failed: {detail}")
	return result


def _resolve_repository(note_path, repo_root: Path | None = None, initialize=False):
	note_root = Path(note_path).expanduser().resolve()
	expected_root = (
		Path(repo_root).expanduser().resolve()
		if repo_root is not None
		else note_root
	)

	if not expected_root.is_dir():
		raise CommandError(f"Repository root is not a directory: {expected_root}")

	try:
		note_root.relative_to(expected_root)
	except ValueError as error:
		raise CommandError(
			f"NOTE_PATH is outside the configured repository root: {expected_root}"
		) from error

	probe = subprocess.run(
		["git", "-C", str(note_root), "rev-parse", "--show-toplevel"],
		check=False,
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
	)
	if probe.returncode:
		if initialize and expected_root == note_root:
			_run_git(note_root, "init")
			actual_root = note_root
		else:
			detail = (probe.stderr or probe.stdout).strip()
			raise CommandError(
				f"Expected Git repository at {expected_root}: {detail}"
			)
	else:
		actual_root = Path(probe.stdout.strip()).resolve()

	if actual_root != expected_root:
		if repo_root is None:
			raise CommandError(
				"NOTE_PATH is inside a parent Git repository. "
				f"Pass --repo-root {actual_root} to authorize that repository root."
			)
		raise CommandError(
			f"Configured repository root {expected_root} does not match {actual_root}"
		)

	return actual_root, note_root.relative_to(actual_root)


def _notebook_pathspecs(relative_note_path):
	root = relative_note_path.as_posix()
	private_paths = tuple((relative_note_path / path).as_posix() for path in (
		"pnbp_settings.json", ".pnbp/secrets.json", ".pnbp/legacy-settings.json", ".pnbp/drafts", ".pnbp/metadata.lock", ".pnbp/operations",
	))
	include = "." if root == "." else f":(top,literal){root}"
	excludes = tuple(f":(top,literal,exclude){path}" for path in private_paths) + (
		":(top,glob,exclude)**/.pnbp/.secrets-*.tmp",
		":(top,glob,exclude)**/.pnbp/.metadata-*.tmp",
		":(top,glob,exclude)**/.pnbp-change-*.tmp",
	)
	return include, excludes, private_paths


def _staged_paths(repository):
	result = _run_git(repository, "diff", "--cached", "--name-only", "-z")
	return tuple(path for path in result.stdout.split("\0") if path)


def _path_is_within_notebook(path, relative_note_path):
	if relative_note_path == Path("."):
		return True
	note_path = PurePosixPath(relative_note_path.as_posix())
	candidate = PurePosixPath(path)
	return candidate == note_path or note_path in candidate.parents


def _unstage_notebook(repository, include):
	result = subprocess.run(
		["git", "-C", str(repository), "reset", "--quiet", "--", include],
		check=False,
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
	)
	if result.returncode:
		detail = (result.stderr or result.stdout).strip()
		raise CommandError(
			f"Git operation failed and notebook changes could not be unstaged: {detail}"
		)


@option('--repo-root', help='Expected Git repository root. Required when NOTE_PATH is inside a parent repository.')
@pass_nb
def _git_commit_notebook(repo_root: Path | None = None, nb=None):
	"""Commit notebook changes to a verified local Git repository."""
	repository, relative_note_path = _resolve_repository(
		nb.NOTE_PATH,
		repo_root=repo_root,
		initialize=True,
	)
	include, excludes, private_paths = _notebook_pathspecs(relative_note_path)

	preexisting = _staged_paths(repository)
	if preexisting:
		raise CommandError(
			"Git already has staged changes; commit or unstage them before running notebook automation."
		)

	candidates = _run_git(
		repository, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", include, *excludes,
	).stdout.split("\0")
	pathspecs = "".join(f":(top,literal){path}\0" for path in dict.fromkeys(candidates) if path)
	if pathspecs:
		_run_git(repository, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", input=pathspecs)
	staged = _staged_paths(repository)
	if not staged:
		print("No notebook changes to commit.")
		return None

	unexpected = tuple(
		path
		for path in staged
		if (
			not _path_is_within_notebook(path, relative_note_path)
			or path in private_paths
		)
	)
	if unexpected:
		_unstage_notebook(repository, include)
		raise CommandError(
			"Refusing to commit paths outside the notebook scope: "
			+ ", ".join(unexpected)
		)

	timestamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
	try:
		result = _run_git(
			repository,
			"commit",
			"-m",
			f"Automated notebook commit at {timestamp}",
		)
	except CommandError:
		_unstage_notebook(repository, include)
		raise

	print(result.stdout.strip())
	return _run_git(repository, "rev-parse", "HEAD").stdout.strip()


@option('--repo-root', help='Expected Git repository root. Required when NOTE_PATH is inside a parent repository.')
@pass_nb
def _collect_git_diff(repo_root: Path | None = None, nb=None):
	"""Write the notebook-scoped Git diff to ``all diff.md``."""
	repository, relative_note_path = _resolve_repository(
		nb.NOTE_PATH,
		repo_root=repo_root,
	)
	include, excludes, _ = _notebook_pathspecs(relative_note_path)
	result = _run_git(repository, "diff", "--", include, *excludes)
	if not (diff := result.stdout.strip()):
		return ""

	file_line = r"diff --git a/(.+) b/(.+)"
	a_line = r"--- a/(.+)"
	b_line = r"\+\+\+ b/(.+)"
	diff_dict = {}
	current = ""
	removed = []
	added = []
	lines = diff.splitlines()

	for index, line in enumerate(lines):
		if (match := re.match(file_line, line)) or index == len(lines) - 1:
			if current and (removed or added):
				diff_dict[current] = [removed, added]
			if index != len(lines) - 1:
				current = match.group(1)
				removed = []
				added = []

		if current:
			if line.startswith("-") and not re.match(a_line, line):
				if len(line) > 1:
					removed.append("\\" + line[1:] if line[1:].strip() == "---" else line[1:])
			elif line.startswith("+") and not re.match(b_line, line) and len(line) > 1:
				added.append("\\" + line[1:] if line[1:].strip() == "---" else line[1:])

	datetime_text = _convert_datetime("now")
	note_text = f"\ngit diff: ({datetime_text})\n\n--- \n\n"
	for path, changes in diff_dict.items():
		note_text += f"#### [[{path.replace('.md', '')}]]\n"
		note_text += "**ADDED**: \n{}\n\n\n".format("\n".join(changes[1]))
		note_text += "**REMOVED**: \n{}\n\n--- \n\n".format("\n".join(changes[0]))

	return nb.generate_note("all diff", note_text, overwrite=True)


@option('--path', default='.')
def _init_git_ignore(path):
	"""Append essential patterns to ``.gitignore`` without replacing existing rules."""
	root = Path(path).expanduser().resolve()
	if not root.is_dir():
		raise CommandError(f"Path is not a directory: {root}")

	gitignore = root / ".gitignore"
	if gitignore.is_symlink():
		raise CommandError("Refusing to replace a symlinked .gitignore")

	existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
	existing_lines = set(existing.splitlines())
	missing = [pattern for pattern in _GITIGNORE_PATTERNS if pattern not in existing_lines]
	if missing:
		updated = existing
		if updated and not updated.endswith("\n"):
			updated += "\n"
		updated += "\n".join(missing) + "\n"
		gitignore.write_text(updated, encoding="utf-8")

	print(f".gitignore --> {root}")
	return gitignore
