import subprocess
import sys
import inspect
import json
from dataclasses import asdict
from functools import wraps
from pathlib import Path

from expose_interface import CommandError, Context, Interface, UsageError, argument, flag, option
import requests

from ._internal.cli_tools import edit_text, existing_file, limit_value, offset_value

from .commands import collect
from .commands import commit
from .commands import correct
from .commands import code
from .commands import graph
from .commands import pprint
from .commands import subl
from .commands import tasks
from .commands.deploy import deploy

from .models import Notebook
from .helpers import arrow_call
from pretty_notebook._internal.storage import retain_edit_draft
from pretty_notebook._internal import identities as _identities
from .settings import initialize_notebook, resolve_notebook_path, SettingsError



@option("--notebook", dest="notebook_path", help="Open this notebook path.")
@option("--profile", dest="notebook_profile", help="Open a registered local notebook profile.")
def _setup(context: Context, notebook_path: Path | None = None, notebook_profile: str | None = None):
	if notebook_path is not None and notebook_profile is not None:
		raise UsageError("Choose --notebook or --profile, not both.")
	if notebook_path is not None and not notebook_path.is_dir():
		raise UsageError("--notebook must be an existing directory.")
	selection = {"path": notebook_path} if notebook_path is not None else {"profile": notebook_profile} if notebook_profile is not None else {}
	context.obj = {"selection": selection, "notebook": None}


app = Interface("pnbp", setup=_setup)
app.add_interface(deploy)
cli = app.main


def _open_notebook(context):
	state = context.obj
	if state["notebook"] is None:
		try:
			state["notebook"] = Notebook(**state["selection"])
		except (SettingsError, ImportError, OSError) as error:
			raise CommandError(str(error)) from error
	return state["notebook"]


def _command_errors(func):
	@wraps(func)
	def invoke(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except (SettingsError, ValueError, OSError, RuntimeError, KeyError) as error:
			raise CommandError(str(error)) from error
	return invoke


def _json_echo(payload, notebook):
	"""Serialize allowlisted reports with bounded text and token redaction."""
	def clean(value):
		if isinstance(value, str):
			if notebook.API_TOKEN:
				value = value.replace(notebook.API_TOKEN, "<redacted>")
			return value[:4096]
		if isinstance(value, (list, tuple)):
			return [clean(item) for item in value]
		if isinstance(value, dict):
			return {key: clean(item) for key, item in value.items()}
		return value
	print(json.dumps(clean(payload), ensure_ascii=False))


def _note_name(name):
	name = name.strip().replace("\\", "/")
	if not name or any(part in Notebook.SKIP_DIRECTORIES for part in Path(name).parts):
		raise ValueError("Choose a note name outside reserved state directories.")
	return name


def _selected_note(notebook, name):
	name = _note_name(name)
	key = name[:-3] if name.lower().endswith(".md") else name
	if key in notebook.notes:
		return notebook.notes[key]
	return notebook.open_note(name if name.lower().endswith(".md") else name + ".md")


def _source_text(content, source, *, default=""):
	if content is not None and source is not None:
		raise UsageError("Choose --content or --file, not both.")
	return (sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")) if source is not None else content if content is not None else default


@app.program(name="init")
@argument('path', required=False)
@flag('--migrate', help='Migrate legacy settings and retain a private original backup.')
@flag('--dry-run', help='Validate and show the plan without creating or changing files.')
@option('--profile', help='Register a named local notebook profile.')
@_command_errors
def init_notebook(context: Context, *, path: Path | None = None, migrate: bool = False, dry_run: bool = False, profile = None):
	"""Explicitly initialize settings and identities; never initialize Git."""
	try:
		if path is None:
			selection = context.obj["selection"]
			path = resolve_notebook_path(**selection) if selection else Path(".")
		initialize_notebook(path, migrate=migrate, dry_run=True, profile=profile)
		identity_plan = _identities.initialize_identities(path, dry_run=True)
		plan = initialize_notebook(path, migrate=migrate, dry_run=dry_run, profile=profile)
		if not dry_run:
			identity_plan = _identities.initialize_identities(path)
	except (SettingsError, ImportError, OSError) as error:
		raise CommandError(str(error)) from error
	print(json.dumps({**plan.to_dict(), "identities": identity_plan, "dry_run": dry_run}, indent=2))


identity_commands = app.add_interface(Interface("identity", description="Inspect, reconcile, or deliberately fork local identities."))


@identity_commands.program(name="status")
@flag('--json', dest='output_json')
@option('--limit', type=limit_value, default=200)
@_command_errors
def identity_status(context: Context, *, output_json: bool = False, limit = 200):
	nb = _open_notebook(context)
	report = nb.identity_status(limit=limit)
	if output_json:
		_json_echo(report, nb)
	else:
		print(json.dumps(report, ensure_ascii=False, indent=2))


@identity_commands.program(name="reconcile")
@argument('old_path')
@argument('new_path')
@flag('--dry-run')
@_command_errors
def reconcile_identity(context: Context, old_path, new_path, *, dry_run: bool = False):
	nb = _open_notebook(context)
	_json_echo(_identities.reconcile_identity(nb.NOTE_PATH, old_path, new_path, dry_run=dry_run), nb)


@identity_commands.program(name="fork")
@flag('--dry-run')
@_command_errors
def fork_identity(context: Context, *, dry_run: bool = False):
	nb = _open_notebook(context)
	_json_echo(nb.fork_identities(dry_run=dry_run), nb)


note_commands = app.add_interface(Interface("note", description="Add, read, and edit notes with explicit saves."))


@note_commands.program(name="add")
@argument('name')
@option('--content', help='Initial Markdown text, including an explicit empty string.')
@option('--file', dest='source', help="Read Markdown from a file or '-' for stdin.")
@_command_errors
def note_add(context: Context, name, *, content = None, source = None):
	nb = _open_notebook(context)
	created = nb.generate_note(_note_name(name), _source_text(content, source))
	print(f"Created {created.source_path}")


@note_commands.program(name="show")
@argument('name')
@flag('--html', dest='as_html', help='Render through the existing notebook renderer.')
@_command_errors
def note_show(context: Context, name, *, as_html: bool = False):
	nb = _open_notebook(context)
	note = _selected_note(nb, name)
	print(nb.convert_to_html(note) if as_html else note.current_md, end="")


@note_commands.program(name="edit")
@argument('name')
@option('--content', help='Replacement Markdown, including an explicit empty string.')
@option('--file', dest='source', help="Read replacement Markdown from a file or '-' for stdin.")
@_command_errors
def note_edit(context: Context, name, *, content = None, source = None):
	nb = _open_notebook(context)
	note = _selected_note(nb, name)
	edited = _source_text(content, source, default=None)
	if content is None and source is None:
		edited = edit_text(note.current_md)
	if edited is None:
		print("No changes saved.")
		return
	note.md_out = edited
	try:
		saved = note.save(nb)
	except (OSError, RuntimeError, _identities.IdentityError) as error:
		try:
			draft = retain_edit_draft(nb.NOTE_PATH, edited)
		except OSError:
			raise CommandError("Save failed and a recovery draft could not be written.") from error
		raise CommandError(f"Save failed: {error}. Draft retained at {draft}") from error
	print(f"Saved {saved.source_path}")


@note_commands.program(name="rename")
@argument('source')
@argument('new_name')
@flag('--dry-run')
@_command_errors
def note_rename(context: Context, source, new_name, *, dry_run: bool = False):
	"""Rename within the current directory and repair matching wiki targets."""
	nb = _open_notebook(context)
	_json_echo(nb.rename_note(source, new_name, dry_run=dry_run), nb)


@note_commands.program(name="move")
@argument('source')
@argument('destination')
@flag('--dry-run')
@_command_errors
def note_move(context: Context, source, destination, *, dry_run: bool = False):
	"""Move to a notebook-relative path with recoverable backlink updates."""
	nb = _open_notebook(context)
	_json_echo(nb.move_note(source, destination, dry_run=dry_run), nb)


@note_commands.program(name="operations")
@option('--limit', type=limit_value, default=200)
@_command_errors
def note_operations(context: Context, *, limit = 200):
	"""List local move journals and their recovery state."""
	nb = _open_notebook(context)
	_json_echo({"operations": nb.move_operations(limit=limit)}, nb)


@note_commands.program(name="recover")
@argument('operation_id')
@option('--action', choices=['resume', 'rollback'], default='resume')
@flag('--dry-run')
@_command_errors
def note_recover(context: Context, operation_id, *, action = 'resume', dry_run: bool = False):
	"""Resume or roll back a checked local move journal."""
	nb = _open_notebook(context)
	_json_echo(nb.recover_move(operation_id, action=action, dry_run=dry_run), nb)


@app.program(name="search")
@argument('query')
@option('--field', choices=['content', 'title', 'tag', 'any'], default='content', help='Choose the matching note field.')
@option('--tag', dest='tags', multiple=True, help='Require this exact tag; repeat to require every tag.')
@flag('--regex', help='Treat the query as a local regular expression.')
@option('--limit', type=limit_value, default=50)
@option('--offset', type=offset_value, default=0)
@flag('--json', dest='output_json')
@_command_errors
def search_notes(context: Context, query, *, field = 'content', tags: tuple[str, ...] = (), regex: bool = False, limit = 50, offset = 0, output_json: bool = False):
	"""Search local notes using literal, case-insensitive matching by default."""
	nb = _open_notebook(context)
	hits = nb.search(query, field=field, tags=tags, regex=regex, limit=limit, offset=offset)
	if output_json:
		_json_echo({"hits": [asdict(hit) for hit in hits], "limit": limit, "offset": offset}, nb)
	else:
		for hit in hits:
			print(f"{hit.name}: {hit.excerpt}")


@app.program(name="status")
@flag('--json', dest='output_json')
@option('--limit', type=limit_value, default=50)
def notebook_status(context: Context, *, output_json: bool = False, limit = 50):
	nb = _open_notebook(context)
	unsaved = nb.unsaved_notes
	report = {
		"path": nb.NOTE_PATH, "notes": len(nb), "note_nested": nb.settings.note_nested,
		"settings_file": nb.settings_file, "api_configured": bool(nb.API_BASE),
		"unsaved": [note.name for note in unsaved[:limit]], "unsaved_count": len(unsaved),
		"truncated": len(unsaved) > limit,
	}
	if output_json:
		_json_echo(report, nb)
	else:
		print(f"{nb.NOTE_PATH}: {len(nb)} notes, {len(unsaved)} pending edits")


@app.program(name="doctor")
@flag('--json', dest='output_json', help='Print a bounded diagnostic report as JSON.')
def doctor(context: Context, *, output_json: bool = False):
	"""Inspect notebook configuration, access, identities and runtime packages without writes."""
	from ._internal.diagnostics import diagnose_notebook
	report = diagnose_notebook(context.obj['selection'])
	if output_json:
		print(json.dumps(report))
	else:
		for check in report['checks']:
			print(f"{check['status']}: {check['check']}: {check['message']}")
	if not report['ok']:
		raise SystemExit(1)



""" Pretty-Notebook/apps/web api connection commands:
"""
def _publish_notebook(notebook, **kwargs):
	"""Run publication with concise CLI reporting for transport failures."""
	try:
		return notebook.post_commits_to_web_api(**kwargs)
	except requests.RequestException as error:
		raise CommandError(f'Publication failed: {error}') from error


@app.program
def commit_html(context: Context):
	""" if note contains #public, -> HTML_PATH/.html 
		(for local debugging when running remote server 
		and not a concurrent localhost instance...)
	"""
	# ^^ docstring == help message
	nb = _open_notebook(context)
	nb.write_commits_to_local_html()


@app.program
@flag('--prune', help='Remove every remote page absent from this notebook after successful uploads.')
@flag('--refresh-images', help='Resend referenced images even when their names already exist remotely.')
@option('--mode', choices=['auto', 'checked', 'legacy'], default='auto')
@flag('--accept-remote', help='Use reviewed current remote versions after a sync conflict.')
@_command_errors
def commit_remote(context: Context, *, prune: bool = False, refresh_images: bool = False, mode = 'auto', accept_remote: bool = False):
	""" if note contains #public, -> 
		selective update POST to .../apps/web api
		@ {API_BASE}/api/publishment
	"""
	nb = _open_notebook(context)
	_publish_notebook(nb, prune=prune, refresh_images=refresh_images, mode=mode, accept_remote=accept_remote)


@app.program
@flag('--prune', help='Remove every remote page absent from this notebook after successful uploads.')
@flag('--refresh-images', help='Resend referenced images even when their names already exist remotely.')
@option('--mode', choices=['auto', 'checked', 'legacy'], default='auto')
@flag('--accept-remote', help='Use reviewed current remote versions after a sync conflict.')
@_command_errors
def commit_local(context: Context, *, prune: bool = False, refresh_images: bool = False, mode = 'auto', accept_remote: bool = False):
	""" commit -> localhost .../apps/web instance
	""" # a convenience command
	nb = _open_notebook(context)
	nb.API_BASE = 'http://127.0.0.1:8000'
	_publish_notebook(nb, prune=prune, refresh_images=refresh_images, mode=mode, accept_remote=accept_remote)


@app.program
@flag('--json', dest='output_json')
@option('--limit', type=limit_value, default=200)
@option('--mode', choices=['auto', 'checked', 'legacy'], default='auto')
@flag('--prune', help='Preview deletion of unlisted remote pages.')
@flag('--refresh-images')
@flag('--accept-remote', help='Preview using reviewed current remote versions after a sync conflict.')
@_command_errors
def commit_stage(context: Context, *, output_json: bool = False, limit = 200, mode = 'auto', prune: bool = False, refresh_images: bool = False, accept_remote: bool = False):
	""" *only* print commit- changes against nb.API_BASE
		to the terminal (staging view)
	"""
	nb = _open_notebook(context)
	if output_json:
		try:
			_json_echo(nb.publication_plan(limit=limit, mode=mode, prune=prune, refresh_images=refresh_images, accept_remote=accept_remote), nb)
		except requests.RequestException as error:
			raise CommandError("Could not read the remote publication inventory.") from error
	else:
		_publish_notebook(nb, stage_only=True, mode=mode, prune=prune, refresh_images=refresh_images, accept_remote=accept_remote)


@app.program
@flag('--local', default=False, help='post to localhost instead of the configured API_BASE')
def commit_settings(context: Context, *, local: bool = False):
	"""Send configured layout settings to the web API.
	"""
	nb = _open_notebook(context)
	
	if local:
		nb.API_BASE = 'http://127.0.0.1:8000'
		
	nb.web_settings_post()


@app.program
@argument('path', type=existing_file)
@flag('--local', help='Upload to localhost instead of the configured API_BASE.')
@_command_errors
def favicon(context: Context, path, *, local: bool = False):
	"""Replace the site's PNG favicon using site-owner credentials."""
	nb = _open_notebook(context)
	if local:
		nb.API_BASE = "http://127.0.0.1:8000"
	try:
		response = nb.post_favicon(path)
	except requests.RequestException as error:
		raise CommandError("Could not update the site favicon.") from error
	print(response.json()["url"])


@app.program
def git_clone_pnbp_web():
	""" command to clone from github to ./pnbp_web/
	"""
	cmd = ["git", "clone", "--filter=blob:none", 
			"--sparse", "--depth", "1", "--single-branch", 
			"--branch", "main", "https://github.com/outside-labs/pretty-notebook.git",
			"pnbp-web"]

	cmd2 = ["git", "-C", "pnbp-web", "sparse-checkout", "set", "apps/web"]
		
	op = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
		
	print(op.stderr) # git outputs stdout to stderr

	wp = subprocess.run(cmd2, capture_output=True, text=True, errors="replace")
	
	print(wp.stderr)



@app.program(name='logs')
@flag('--remote', help='Read authenticated server events for the selected notebook.')
@option('--limit', type=int, default=100)
@option('--before', type=int, default=0)
@_command_errors
def logs(context: Context, *, remote: bool = False, limit: int = 100, before: int = 0):
	"""Read bounded operation receipts without note contents or credentials."""
	from .commands.logs import operation_logs
	nb = _open_notebook(context)
	_json_echo(operation_logs(nb, remote=remote, limit=limit, before=before), nb)


def _create_command(function):
	"""Adapt legacy notebook functions to an invocation-local native program."""
	parameters = inspect.signature(function).parameters

	@wraps(function)
	def invoke(context, **kwargs):
		if "nb" in parameters:
			kwargs["nb"] = _open_notebook(context)
		if function.__name__.startswith("_collect") and "nb" in kwargs:
			from ._internal.operation_logs import operation
			with operation(kwargs["nb"].NOTE_PATH, "collect"):
				return function(**kwargs)
		return function(**kwargs)

	inputs = [inspect.Parameter("context", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context)]
	annotations = {"context": Context}
	for name, parameter in parameters.items():
		if name == "nb":
			continue
		if name == "note":
			parameter = parameter.replace(annotation=str, default=inspect.Parameter.empty)
		annotations[name] = parameter.annotation
		inputs.append(parameter.replace(kind=inspect.Parameter.KEYWORD_ONLY))
	if "note" in parameters:
		inputs.append(inspect.Parameter("fuzzy", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool))
		annotations["fuzzy"] = bool
		invoke = option("-n", "--note", required=True, type=str, help="The name of a note.")(invoke)
		invoke = flag("--fuzzy", help="Explicitly accept the closest matching note name.")(invoke)
	invoke.__signature__ = inspect.Signature(inputs)
	invoke.__annotations__ = {name: value for name, value in annotations.items() if value is not inspect.Parameter.empty}
	invoke.__name__ = function.__name__.lstrip("_")
	return app.program(name=invoke.__name__.replace("_", "-"))(_command_errors(arrow_call(invoke)))


def create_command(function):
	"""Register a notebook command while preserving its direct Python callable."""
	command = _create_command(function)
	setattr(sys.modules[__name__], function.__name__.lstrip("_"), command)


BUILTIN_COMMANDS = (
	collect._collect_all_stats, collect._collect_all_notes, collect._collect_all_urls,
	collect._collect_all_public, collect._collect_terms, collect._collect_all_unlinked,
	collect._collect_all_empty, collect._collect_all_unheadered, collect._collect_all_moc,
	collect._collect_all_tags, collect._collect_nonexistant_links, collect._collect_all,
	collect._collect_code_blocked, collect._collect_tasks_note, collect._collect_public_graph,
	collect._collect_all_graphs, collect._collect_subl_projs,
	commit._git_commit_notebook, commit._collect_git_diff, commit._init_git_ignore,
	correct._strip_links_spacing, correct._expand_links_spacing, correct._prepend_leading_newline,
	correct._remove_leading_newline, correct._remove_leading_and_trailing_newlines,
	correct._link_unlinked_mentions, correct._collect_unlinked_mentions,
	correct._remove_nonexistant_links, correct._delete_all_pnbp, correct._delete_all_empty,
	correct._touch_all_public,
	code._extract_code_blocks, code._extract_all_code_blocks,
	graph._create_link_graph, graph._create_tag_graph, graph._delete_all_graph_dash_name,
	pprint._pprint, subl._subl_init, tasks._task_settle,
)


def create_all_commands():
	"""Register the explicit supported command list without scanning private helpers."""
	for func in BUILTIN_COMMANDS:
		create_command(func)


# -> required to call here (pre-main) for pyproject.toml / 
# pip install to recognize dynamically created commands
create_all_commands()

if __name__ == '__main__':
	cli()
	
