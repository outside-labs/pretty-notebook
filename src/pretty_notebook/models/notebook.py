import re
import difflib
import mimetypes
import random

from collections.abc import Iterator
from pathlib import Path

import requests as requests

from pretty_notebook.settings import load_settings
from pretty_notebook._internal import storage as _storage, rendering as _rendering, search as _search, publishing as _publishing, identities as _identities, links as _links, moves as _moves, journal as _journal, routes as _routes, navigation as _navigation

from .note import Note

from .components import Link



class _NotebookOpen:
	"""Keep instance reloads compatible while exposing a class-level opener."""

	def __get__(self, instance, owner):
		return owner._open_path if instance is None else instance.reload


class Notebook:
	""" 
	"""
	SKIP_DIRECTORIES = {".git", ".obsidian", ".pnbp", "__pycache__"}
	PUBLICATION_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
	PUBLICATION_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
	REQUEST_TIMEOUT = (5, 30)

	def __init__(self, path=None, settings=None, *, profile=None, settings_file=None, api_token=None):
		"""Read a notebook without prompts or initialization writes."""
		loaded = load_settings(path, settings, profile=profile, settings_file=settings_file, api_token=api_token)
		self.NOTE_PATH = str(loaded.root)
		self.settings = loaded.settings
		self.settings_file = loaded.settings_file
		self.credentials_file = loaded.credentials_file
		self.config = loaded.config
		for name in ("IMG_PATH", "HTML_PATH", "VENV_PATH"):
			value = getattr(self.settings, name.lower())
			if value:
				value = str((loaded.root / Path(value).expanduser()).resolve())
			setattr(self, name, value)
		self.API_BASE = self.settings.api_base
		self.API_TOKEN = loaded.api_token
		self.PUB_LNK_ONLY = self.settings.pub_lnk_only
		self.COMMIT_TAG = self.settings.commit_tag
		self.EXCLUDE_TAG = self.settings.exclude_tag
		self._identity_index = None
		self._identity_paths = {}
		self.identity_error = None
		self.notes = {}
		self.open_md()

	@classmethod
	def _open_path(cls, path=None, **kwargs):
		"""Open an existing notebook by path or a registered local profile."""
		return cls(path, **kwargs)

	open = _NotebookOpen()

	@property
	def notebook_id(self):
		return self._identity_index.notebook_id if self._identity_index else None

	def _set_identity_index(self, index):
		self._identity_index = index
		self._identity_paths = index.by_path() if index is not None else {}
		self.identity_error = None

	def identity_status(self, *, limit=200):
		"""Inspect missing/corrupt identity state and external moves without writing."""
		return _identities.identity_status(self.NOTE_PATH, limit=limit)

	def graph_index(self):
		"""Rebuild a read-only graph over all notes, including current pending text."""
		pending = {note.source_path: note.current_md for note in self.notes.values() if note.md_out is not None and note.source_path}
		return _links.GraphIndex.from_root(self.NOTE_PATH, pending=pending)

	def resolve_link(self, target, *, source=None):
		"""Resolve a target without fuzzy matching; inspect state before using path."""
		return self.graph_index().resolve(target, source=source)

	def navigation_index(self, *, public_only=False) -> _navigation.NavigationIndex:
		"""Generate a read-only navigation snapshot from current loaded notes."""
		return _navigation.NavigationIndex(self, public_only=public_only)

	def traversal(self, *, public_only=False, limit=200) -> _navigation.NavigationHistory:
		"""Create independent opt-in visit history; ordinary lookups never record it."""
		return _navigation.NavigationHistory(self, public_only=public_only, limit=limit)

	def rename_note(self, source, new_name, *, dry_run=False):
		"""Rename within the source directory, preserving identity and backlinks."""
		return _moves.move_note(self, source, new_name, rename=True, dry_run=dry_run)

	def move_note(self, source, destination, *, dry_run=False):
		"""Move to a notebook-relative path using a checked, recoverable journal."""
		return _moves.move_note(self, source, destination, dry_run=dry_run)

	def move_operations(self, *, limit=200):
		return _journal.operations(self.NOTE_PATH, limit=limit)

	def recover_move(self, operation_id, *, action="resume", dry_run=False):
		return _moves.recover_move(self, operation_id, action=action, dry_run=dry_run)

	def export_identities(self):
		"""Return a portable, independent identity manifest with unchanged UUIDs."""
		index = _identities.load_index(self.NOTE_PATH)
		if index is None:
			raise _identities.IdentityError("Initialize identities before exporting their manifest.")
		return index.to_dict()

	def initialize_identities(self, *, dry_run=False):
		"""Explicitly assign identities; discovery never initializes this state."""
		plan = _identities.initialize_identities(self.NOTE_PATH, dry_run=dry_run)
		if not dry_run:
			self._set_identity_index(_identities.load_index(self.NOTE_PATH))
			for note in self.notes.values():
				note._identity_record = self._identity_paths.get(note.source_path)
		return plan

	def fork_identities(self, *, dry_run=False):
		"""Create a new notebook/note namespace, retaining the previous index."""
		plan = _identities.fork_identities(self.NOTE_PATH, dry_run=dry_run)
		if not dry_run:
			self._set_identity_index(_identities.load_index(self.NOTE_PATH))
			for note in self.notes.values():
				note._identity_record = self._identity_paths.get(note.source_path)
		return plan

	def __len__(self):
		""" the number of notes """
		return len(self.notes.keys())

	@property
	def unsaved_notes(self)->tuple:
		""" return a tuple of all notes that have unsaved changes
		"""
		return tuple(note for note in self.notes.values() if note.is_unsaved)
	
	@property
	def has_unsaved_notes(self)->bool:
		""" return True if any note has unsaved changes, False otherwise
		"""
		return bool(self.unsaved_notes)
	
	def save_all_notes(self):
		""" save all notes that have unsaved changes
		"""
		if not self.has_unsaved_notes:
			print("no unsaved notes to save.")
			return []

		names = [note.name for note in self.unsaved_notes]

		from pretty_notebook._internal.operation_logs import operation
		with operation(self.NOTE_PATH, "flush"):
			for name in names:
				self.notes[name].save(self)

		return names

	def discard_all_changes(self):
		""" discard all changes to all notes that have unsaved changes
		"""
		if not self.has_unsaved_notes:
			print("no unsaved notes with content to discard.")
			return []

		names = [note.name for note in self.unsaved_notes]

		for name in names:
			self.notes[name].discard_changes()

		return names

	def _iter_note_files(self) -> Iterator[Path]:
		""" an internal method to safely iterate the "flat" self.NOTE_PATH/
			directory, a "single", or full "recur"(sive) path, 
			including (if advised, not by default) "all" (i.e. incl. hidden)
		"""
		return _storage.iter_note_files(self)

	def open_note(self, f, *, notes=None):
		""" 
		:param str f: the .md note to open
		:param dict notes: optional destination mapping used during atomic reloads
		"""
		note = _storage.read_note(self, f)
		note._identity_record = self._identity_paths.get(note.source_path)
		target = self.notes if notes is None else notes
		target[note.name] = note
		return note

	def open_md(self, *, discard_unsaved=False)->dict:
		""" open all .md files from the self.NOTE_PATH path
			into memory as e.g. {"my note name": Note}
			-> available at nb.notes

		:param bool discard_unsaved: explicitly allow pending edits to be discarded
		"""
		if self.has_unsaved_notes and not discard_unsaved:
			names = ", ".join(note.name for note in self.unsaved_notes)
			raise RuntimeError(
				f"Cannot reload notebook with unsaved changes: {names}. "
				"Save them or call open_md(discard_unsaved=True)."
			)

		root = Path(self.NOTE_PATH).expanduser().resolve()
		loaded_notes = {}
		previous = self._identity_index, self._identity_paths, self.identity_error
		try:
			try:
				self._set_identity_index(_identities.load_index(root))
			except _identities.IdentityError as error:
				self._set_identity_index(None)
				self.identity_error = str(error)
			for path in self._iter_note_files():
				relative_path = path.relative_to(root)
				self.open_note(relative_path.as_posix(), notes=loaded_notes)
		except BaseException:
			self._identity_index, self._identity_paths, self.identity_error = previous
			raise

		self.notes = dict(sorted(loaded_notes.items()))

		return self.notes

	def reload(self, *, discard_unsaved=False):
		"""Reload from disk; pending edits require explicit discard authorization."""
		self.open_md(discard_unsaved=discard_unsaved)

	def _require_clean_notes(self, operation):
		"""Refuse operations that cannot safely consume staged note content."""
		if self.has_unsaved_notes:
			names = ", ".join(note.name for note in self.unsaved_notes)
			raise RuntimeError(
				f"Cannot {operation} with unsaved changes: {names}. "
				"Save or discard them explicitly first."
			)

	def generate_note(self, name, md_out, overwrite=False, pnbp=False):
		""" 
		:param name: the name of the note (without ".md") to generate
		:param md_out: the desired string to save to the notebook at "name.md"
		:param overwrite: if overwrite=True, allow existing file to be re-written
		:param pnbp: if pnbp=True, tagging #pnbp to track and ignore
		"""
		return _storage.generate_note(self, name, md_out, overwrite, pnbp)

	def get(self, name, *, fuzzy=True)->Note:
		"""Resolve a note exact-first, with optional fuzzy fallback.

		:param name: name of the note
		:param bool fuzzy: allow a close-match fallback after exact resolution
		:returns: Note instance or None
		"""
		if isinstance(name, Note):
			return self.notes.get(name.name)

		if hasattr(name, "note"):
			name = name.note

		raw_name = str(name).strip()
		if (note := self.notes.get(raw_name)):
			return note

		normalized_name = raw_name.replace('\\', '/')
		if (note := self.notes.get(normalized_name)):
			return note

		normalized_name = re.sub(
			r'\.(?:md|html)$',
			'',
			normalized_name,
			flags=re.IGNORECASE,
		)
		if (note := self.notes.get(normalized_name)):
			return note

		for n in self.notes.values():
			if n.slugname == normalized_name:
				return n

		if not fuzzy:
			return None

		matches = difflib.get_close_matches(normalized_name, self.notes.keys(), n=1)
		if matches:
			matched_name = matches[0]
			print(f"^^ {matched_name} (by close match) ")
			return self.notes[matched_name]

		print(f"note: `{raw_name}` does not exist in the notebook!")
		return None

	def get_random_note(self):
		"""
		:returns: a random note from the notebook
		"""
		return self.notes[random.choice([k for k in self.notes.keys()])]


	def get_tagged(self, tag)->list:
		""" 
		:param tag: the #tag in question
		:returns: a list of Note instances containing tag
		"""
		t_notes = []
		for n in self.notes.values():
			if n.is_tagged(tag):
				t_notes.append(n)

		return t_notes

	def is_publishable(self, note)->bool:
		"""Return whether a note is explicitly public and not excluded."""
		return (
			note.is_tagged(self.COMMIT_TAG)
			and not note.is_tagged(self.EXCLUDE_TAG)
		)

	def _publication_image(self, reference):
		"""Resolve one flat image reference without allowing IMG_PATH escapes."""
		reference = reference.strip()

		if not reference or not self.IMG_PATH:
			raise ValueError(f"Invalid publication image path: {reference!r}")

		root = Path(self.IMG_PATH).expanduser().resolve()
		supplied = Path(reference).expanduser()

		if supplied.is_absolute() or supplied.name != reference:
			raise ValueError(f"Invalid publication image path: {reference!r}")

		target = (root / supplied).resolve()

		try:
			target.relative_to(root)
		except ValueError as error:
			raise ValueError(
				f"Publication image path escapes IMG_PATH: {reference!r}"
			) from error

		if target.suffix.lower() not in self.PUBLICATION_IMAGE_EXTENSIONS:
			raise ValueError(f"Unsupported publication image path: {reference!r}")

		if not target.is_file():
			raise FileNotFoundError(f"Publication image not found: {reference!r}")

		content_type = mimetypes.guess_type(target.name)[0]
		if content_type is None:
			content_type = "application/octet-stream"

		return target, content_type

	def _publication_preflight(self, *, include_images=False):
		"""Validate all publication inputs before writes or HTTP requests."""
		_journal.ensure_clear(self.NOTE_PATH)
		notes = tuple(note for note in self.notes.values() if self.is_publishable(note))
		_routes.plan_routes(self, notes)

		images = {}
		if include_images:
			for note in notes:
				for reference in re.findall(Link.MDS_IMG_LNK, note.md):
					reference = reference.strip()
					if reference not in images:
						images[reference] = self._publication_image(reference)

		return notes, images

	def publication_routes(self):
		"""Inspect routes, identities, and ambiguous legacy aliases without I/O writes."""
		return _routes.plan_routes(self, tuple(note for note in self.notes.values() if self.is_publishable(note)))

	def get_linked(self, link)->list:
		"""
		:param link: the [[link]] in question
		:returns: a list of Note instances containing link
		"""
		l_notes = []
		for n in self.notes.values():
			if n.is_linked(link):
				l_notes.append(n)

		return l_notes

	@property
	def tags(self)->list:
		""" a list of all found #tags in the Notebook instance
		"""
		ts = []
		for n in self.notes.values():
			for t in n.tags:
				ts.append(t)

		return sorted(list(set(ts)))

	@property
	def links(self):
		""" a list of all .md Notes in the Notebook
		"""
		return sorted([fn for fn in self.notes.keys()])

	@property
	def urls(self)->list:
		""" a list of all Urls found in the Notebook
		"""
		us = []
		for n in self.notes.values():
			for u in n.urls:
				us.append(u)

		return sorted(us)

	def find(self, regex):
		""" a user convenience method to effectively grep notebook
		"""
		return _search.find(self, regex)

	def search(
		self, query: str, *, field: _search.SearchField = "content", tags=(),
		regex: bool = False, limit: int = 50, offset: int = 0,
	) -> list[_search.SearchHit]:
		"""Return quiet, bounded current-note hits with field and exact tag filters."""
		return _search.search(self, query, field=field, tags=tags, regex=regex, limit=limit, offset=offset)

	def find_and_replace(self, regex, replace, notes=[]):
		""" 

		:param regex: 
		:param replace: 
		:param notes: 
		"""
		msg = "Notebook.find_and_replace requires a list of Notes to make replacements."
		if not notes:
			raise ValueError(f"{msg}\nnb.find_and_replace(regex='foo', replace='', notes=nb.find('foo'))")
		elif not isinstance(notes, list):
			raise ValueError(f"{msg}\nnb.find_and_replace(..., notes=[nb.get('bar'))]")
		else:
			# handle for string name -> note gets
			pass

		if (ntc := self.find(regex)):
			ntc = [n for n in ntc if n in notes]
			print('"replace" <- "regex" : n.name')
			for n in ntc:
				n.md_out = re.sub(fr'{regex}', replace, n.md)
				n.save(self)
				print(f'"{replace}" <- "{regex}" : {n.name}')

	""" preparing for api commits : 
	"""
	@classmethod
	def replace_strikethrough(cls, note):
		"""Replace separate ``~~text~~`` spans without crossing whitespace edges.
		
		:param note: an Note instance
		"""
		p = re.compile(r'~~(?=\S)(.+?)(?<=\S)~~')
		strike_repl = lambda m: f'<s>{m.group(1)}</s>'

		if note.md_out is None:
			note.md_out = note.md
		
		note.md_out = p.sub(strike_repl, note.md_out)

		return note

	@classmethod
	def replace_eqhighlight(cls, note):
		"""Replace separate ``==text==`` spans without treating comparisons as markup.
		
		:param note: an Note instance
		"""
		p = re.compile(r'==(?=\S)(.+?)(?<=\S)==')
		eqhl_repl = lambda m: f'<mark>{m.group(1)}</mark>'

		if note.md_out is None:
			note.md_out = note.md
		
		note.md_out = p.sub(eqhl_repl, note.md_out)

		return note

	def remove_nonpub_links(self, note):
		""" if #public note with [[not public]] links,
			remove them from html generation if nb.PUB_LNK_ONLY

		:param note: an Note instance
		""" 
		remv = []
		for link in note.current_links:
			target = self.notes.get(link.note)
			if target is None or not self.is_publishable(target):
				remv.append(str(link))

		note.remove_links(remv)
		# -> md_out is set initially here. 

		return note

	def hide_commit_tag(self, note):
		""" removes the #public tag (aka COMMIT_TAG) from
			the .md before export (if PUB_LNK_ONLY)

		:param note: an Note instance
		"""
		if note.md_out is None:
			# -> if md_out is not set yet...
			note.md_out = note.md

		note.md_out = note.md_out.replace(self.COMMIT_TAG, '')

		return note

	def convert_to_html(self, note):
		"""Render one note while keeping literal code spans opaque to extensions.

		:param note: a Note instance
		"""
		return _rendering.render_note(self, note)
		

	def write_commits_to_local_html(self):
		""" a local debugging mtd 
			-> self.HTML_PATH/.html ... 
		"""
		return _publishing.write_local_html(self)

	""" pnbp-web api connection methods:
	"""
	def get_headers(self):
		""" the request headers """
		return _publishing.headers(self)

	def _api_request(self, method, path, **kwargs):
		"""Send one checked API request with a finite connection/read timeout."""
		return _publishing.request(self, method, path, **kwargs)

	def refresh_token(self):
		""" request method to replace the authenticated user's bearer token 
		"""
		return _publishing.refresh_token(self)

	def get_authed_user(self):
		""" request method to get the authenticated user's username 
		"""
		return _publishing.get_authed_user(self)

	def get_api_home(self):
		""" request method to /api/ (testing auth) 
		"""
		return _publishing.get_api_home(self)

	def get_pub_commits(self)->dict:
		""" (internal use)
			request method for a remote filepath check 
			for the purpose of making smarter POST updates
			against current publishments.
		"""
		return _publishing.get_pub_commits(self)

	def get_img_commits(self)->dict:
		""" (internal use)
			request method for a remote filepath check
			for the purpose of making smarter POST updates
			against current imgs.
		"""
		return _publishing.get_img_commits(self)

	def delete_unlisted_post(self, rname):
		""" (internal use)
			request method to remove the HTML at filepath
			of Note(s) made non- #public
		"""
		return _publishing.delete_unlisted_post(self, rname)

	def post_commits_to_web_api(
		self,
		stage_only=False,
		*,
		prune=False,
		refresh_images=False,
		mode="auto",
		accept_remote=False,
	):
		""" the main POST method

		:param stage_only: if stage_only, print #public and don't commit
		:param prune: remove every remote page absent from this notebook
		:param refresh_images: resend referenced images even when names exist remotely
		"""
		if stage_only:
			return _publishing.post_commits(self, stage_only, prune=prune, refresh_images=refresh_images, mode=mode, accept_remote=accept_remote)
		from pretty_notebook._internal.operation_logs import operation
		with operation(self.NOTE_PATH, "publish"):
			return _publishing.post_commits(self, stage_only, prune=prune, refresh_images=refresh_images, mode=mode, accept_remote=accept_remote)

	def publication_plan(self, *, prune=False, refresh_images=False, limit=200, mode="auto", accept_remote=False):
		"""Preview negotiated publication actions without writing local or remote state."""
		return _publishing.publication_plan(self, prune=prune, refresh_images=refresh_images, limit=limit, mode=mode, accept_remote=accept_remote)

	def prepare_publication(self, *, prune=False, refresh_images=False, mode="checked", accept_remote=False):
		"""Build an immutable checked plan; auto/legacy may return None for a legacy server."""
		from pretty_notebook._internal import publication_plan as _publication_plan
		return _publication_plan.prepare(self, prune=prune, refresh_images=refresh_images, mode=mode, accept_remote=accept_remote)

	def execute_publication(self, plan):
		"""Revalidate and execute one immutable plan with checked writes and receipts."""
		from pretty_notebook._internal import publication_execute as _publication_execute
		return _publication_execute.execute(self, plan)

	def web_settings_post(self):
		""" request method to POST layout update 
			from self.NOTE_PATH/pnbp_settings.json 
			(see https://github.com/outside-labs/pretty-notebook/blob/main/apps/web-settings.json
			for examples)
		"""
		return _publishing.web_settings_post(self)

	def post_favicon(self, path):
		"""Replace the site's PNG favicon; requires site-owner credentials."""
		return _publishing.post_favicon(self, path)

	def create_api_user(self, username='', bootstrap_token=None):
		""" request method to generate an pnbp-web API user 
		"""
		return _publishing.create_api_user(self, username, bootstrap_token)
	
	def reset_api_password(self):
		""" request method to update the authed user's API password 
		"""
		return _publishing.reset_api_password(self)
