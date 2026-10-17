"""Derived local navigation and explicit, independent traversal history."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from pretty_notebook._internal import identities as _identities, links as _links, search as _search


@dataclass(frozen=True)
class NavigationEntry:
	name: str
	path: str
	title: str
	note_id: str | None
	tags: tuple[str, ...]


@dataclass(frozen=True)
class Breadcrumb:
	label: str
	path: str
	is_note: bool = False


@dataclass(frozen=True)
class DirectoryIndex:
	path: str
	directories: tuple[str, ...]
	notes: tuple[NavigationEntry, ...]


@dataclass(frozen=True)
class Heading:
	level: int
	title: str
	anchor: str


@dataclass(frozen=True)
class ReadingNeighbors:
	previous: NavigationEntry | None
	next: NavigationEntry | None


@dataclass(frozen=True)
class RelatedNote:
	note: NavigationEntry
	linked_from: bool
	links_to: bool
	shared_tags: tuple[str, ...]


def _public_option(public_only):
	if type(public_only) is not bool:
		raise ValueError("Navigation public_only must be a boolean.")


def _eligible(notebook, note, public_only):
	if not public_only:
		return True
	return (
		any(tag.matches(notebook.COMMIT_TAG) for tag in note.current_tags)
		and not any(tag.matches(notebook.EXCLUDE_TAG) for tag in note.current_tags)
	)


def _directory_path(path):
	if not isinstance(path, str) or "\\" in path or "\x00" in path:
		raise ValueError("Choose a notebook-relative directory path.")
	if path in {"", "."}:
		return ""
	parts = path.strip("/").split("/")
	if path.startswith("/") or any(part in {"", ".", ".."} | _identities._SKIP_DIRECTORIES for part in parts):
		raise ValueError("Choose a directory inside the notebook and outside reserved state directories.")
	return "/".join(parts)


class NavigationIndex:
	"""A read-only snapshot; rebuild after editing, reloading, or renaming notes.

	Public-only snapshots filter before building relationships or reports. They
	are local projections, rather than a user authorization boundary.
	"""

	def __init__(self, notebook, *, public_only=False):
		_public_option(public_only)
		notes = tuple(note for _, note in sorted(notebook.notes.items()) if _eligible(notebook, note, public_only))
		self.entries = tuple(NavigationEntry(
			note.name, note.source_path or f"{note.name}.md", _search.note_title(note),
			note.note_id, tuple(sorted(map(str, note.current_tags))),
		) for note in notes)
		self._by_path = {entry.path: entry for entry in self.entries}
		self._positions = {entry.path: position for position, entry in enumerate(self.entries)}
		texts = {entry.path: note.current_md for entry, note in zip(self.entries, notes)}
		identities = _identities.IdentityIndex(notebook.notebook_id, tuple(note.identity for note in notes if note.identity)) if notebook.notebook_id else None
		self._graph = _links.GraphIndex(texts, identities)
		self._outlines = {}
		self._control_tags = {"#" + str(tag).lstrip("#").casefold() for tag in (notebook.COMMIT_TAG, notebook.EXCLUDE_TAG, "#pnbp")}

	def entry(self, target, *, source=None) -> NavigationEntry:
		"""Resolve an eligible source name, exact path, identity, or wiki target."""
		if hasattr(target, "source_path"):
			target = target.source_path or f"{target.name}.md"
		elif hasattr(target, "note"):
			target = target.note
		result = self._graph.resolve(target, source=source)
		if result.state != "resolved" or result.path not in self._by_path:
			raise KeyError("Note is not available in this navigation index.")
		return self._by_path[result.path]

	def directory(self, path="", *, recursive=False) -> DirectoryIndex:
		"""Generate an index; empty/unloaded directories have no entries."""
		path = _directory_path(path)
		if type(recursive) is not bool:
			raise ValueError("Navigation recursive must be a boolean.")
		prefix = path + "/" if path else ""
		directories, notes = set(), []
		for entry in self.entries:
			if not entry.path.startswith(prefix):
				continue
			relative = entry.path[len(prefix):]
			if "/" in relative:
				directories.add(prefix + relative.split("/", 1)[0])
			if recursive or "/" not in relative:
				notes.append(entry)
		return DirectoryIndex(path, tuple(sorted(directories)), tuple(notes))

	def breadcrumbs(self, target) -> tuple[Breadcrumb, ...]:
		entry = self.entry(target)
		parts = PurePosixPath(entry.path).parts
		return (
			Breadcrumb("Notebook", ""),
			*(Breadcrumb(part, "/".join(parts[:position + 1])) for position, part in enumerate(parts[:-1])),
			Breadcrumb(entry.title, entry.path, True),
		)

	def outline(self, target) -> tuple[Heading, ...]:
		entry = self.entry(target)
		if entry.path not in self._outlines:
			from pretty_notebook.markdown import render_notebook
			metadata = render_notebook(self._graph.texts[entry.path]).headings
			self._outlines[entry.path] = tuple(Heading(item.level, item.title, item.identifier) for item in metadata)
		return self._outlines[entry.path]

	def backlinks(self, target) -> tuple[NavigationEntry, ...]:
		entry = self.entry(target)
		paths = {source for source, _ in self._graph.backlinks(entry.path)}
		return tuple(self._by_path[path] for path in sorted(paths))

	def neighbors(self, target) -> ReadingNeighbors:
		entry = self.entry(target)
		position = self._positions[entry.path]
		return ReadingNeighbors(
			self.entries[position - 1] if position > 0 else None,
			self.entries[position + 1] if position + 1 < len(self.entries) else None,
		)

	def related(self, target, *, limit=10) -> tuple[RelatedNote, ...]:
		if type(limit) is not int or not 1 <= limit <= 50:
			raise ValueError("Related-note limit must be an integer from 1-50.")
		entry = self.entry(target)
		outgoing = {result.path for source, _, result in self._graph.edges if source == entry.path and result.path}
		incoming = {source for source, _ in self._graph.backlinks(entry.path)}
		tags = {tag.casefold() for tag in entry.tags} - self._control_tags
		results = []
		for candidate in self.entries:
			if candidate.path == entry.path:
				continue
			shared = tuple(sorted(tags & {tag.casefold() for tag in candidate.tags}))
			linked_from, links_to = candidate.path in outgoing, candidate.path in incoming
			if shared or linked_from or links_to:
				results.append(RelatedNote(candidate, linked_from, links_to, shared))
		results.sort(key=lambda result: (-(result.linked_from + result.links_to), -len(result.shared_tags), result.note.path))
		return tuple(results[:limit])


@dataclass(frozen=True)
class _Visit:
	path: str
	note_id: str | None


class NavigationHistory:
	"""Opt-in local visits, independent for each object and never saved to disk."""

	def __init__(self, notebook, *, public_only=False, limit=200):
		_public_option(public_only)
		if type(limit) is not int or not 1 <= limit <= 200:
			raise ValueError("Traversal limit must be an integer from 1-200.")
		self._notebook, self._public_only, self._limit = notebook, public_only, limit
		self._visits, self._position = [], -1

	def _note(self, visit):
		for note in self._notebook.notes.values():
			matches = note.note_id == visit.note_id if visit.note_id else (note.source_path or f"{note.name}.md") == visit.path
			if matches and _eligible(self._notebook, note, self._public_only):
				return note
		return None

	@property
	def current(self):
		"""Resolve the current visit against live loaded notes; missing yields None."""
		return self._note(self._visits[self._position]) if self._position >= 0 else None

	def visit(self, target):
		"""Record an explicit visit; a new branch of visits clears forward history."""
		entry = NavigationIndex(self._notebook, public_only=self._public_only).entry(target)
		visit = _Visit(entry.path, entry.note_id)
		note = self._note(visit)
		if note is self.current:
			return note
		del self._visits[self._position + 1:]
		self._visits.append(visit)
		self._visits = self._visits[-self._limit:]
		self._position = len(self._visits) - 1
		return note

	def _step(self, direction):
		position = self._position + direction
		while 0 <= position < len(self._visits):
			note = self._note(self._visits[position])
			if note is not None:
				self._position = position
				return note
			position += direction
		return None

	def back(self):
		"""Move to the nearest earlier available visit, or leave position unchanged."""
		return self._step(-1)

	def forward(self):
		"""Move to the nearest later available visit, or leave position unchanged."""
		return self._step(1)
