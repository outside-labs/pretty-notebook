"""Source-aware wiki targets and a rebuildable, read-only notebook graph."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from pretty_notebook.markdown.dialect import slugify

from pretty_notebook._internal import identities as _identities, storage as _storage


def _escaped(text, position):
	count = 0
	while position > 0 and text[position - 1] == "\\":
		count += 1
		position -= 1
	return count % 2 == 1


def active_source(text):
	"""Mask literals without changing offsets or newline positions.

	Indented lines are conservatively opaque, including indented list content.
	Unclosed fences remain opaque through EOF. Raw HTML code and comments are
	opaque too; this scanner is a source editing boundary, not a Markdown parser.
	"""
	spans, fence, start, offset = [], None, None, 0
	for line in text.splitlines(keepends=True):
		marker = re.match(r"^[ ]{0,3}(`{3,}|~{3,})(.*?)(?:\r?\n)?$", line)
		if fence is not None:
			if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
				spans.append((start, offset + len(line)))
				fence, start = None, None
		elif marker:
			fence, start = marker[1], offset
		elif line.startswith(("    ", "\t")):
			spans.append((offset, offset + len(line)))
		offset += len(line)
	if fence is not None:
		spans.append((start, len(text)))
	def mask(value, ranges):
		chars = list(value)
		for left, right in ranges:
			chars[left:right] = [char if char in "\r\n" else " " for char in value[left:right]]
		return "".join(chars)
	masked = mask(text, spans)
	html_literals = re.compile(r"<!--.*?(?:-->|$)|<(pre|code|script|style)\b[^>]*>.*?(?:</\1\s*>|$)|<div\b[^>]*class=['\"]mermaid['\"][^>]*>.*?(?:</div\s*>|$)", re.I | re.S)
	masked = mask(masked, [match.span() for match in html_literals.finditer(masked)])
	inline = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
	return mask(masked, [match.span() for match in inline.finditer(masked) if not _escaped(text, match.start())])


@dataclass(frozen=True)
class WikiTarget:
	start: int
	end: int
	target_start: int
	target_end: int
	target: str
	fragment: str | None
	label: str | None
	line: int


def wiki_targets(text):
	"""Yield only active note references, keeping exact target-only spans."""
	masked = active_source(text)
	for match in re.finditer(r"(?<!!)\[\[([^]\r\n]+)\]\]", masked):
		if _escaped(text, match.start()):
			continue
		inside = text[match.start(1):match.end(1)]
		address, separator, label = inside.partition("|")
		name, fragment_separator, fragment = address.partition("#")
		left = match.start(1) + len(name) - len(name.lstrip())
		right = match.start(1) + len(name.rstrip())
		yield WikiTarget(match.start(), match.end(), left, right, name.strip(),
			fragment.strip() if fragment_separator else None,
			label if separator else None, text.count("\n", 0, match.start()) + 1)


@dataclass(frozen=True)
class LinkResolution:
	state: str
	path: str | None = None
	note_id: str | None = None
	candidates: tuple[str, ...] = ()
	heading_state: str | None = None


class GraphIndex:
	"""One snapshot; rebuild after edits rather than treating it as authority."""

	def __init__(self, texts, identities=None):
		self.texts = dict(sorted(texts.items()))
		self.identities = identities.by_path() if identities else {}
		self.notebook_id = identities.notebook_id if identities else None
		self._paths, self._names, self._ids = {}, {}, {}
		for path in self.texts:
			name = PurePosixPath(path).with_suffix("").as_posix()
			self._paths.setdefault(name.casefold(), set()).add(path)
			self._names.setdefault(PurePosixPath(name).name.casefold(), set()).add(path)
			identity = self.identities.get(path)
			if identity:
				self._ids[identity.id] = path
				for alias in (*identity.aliases, *((identity.title,) if identity.title else ())):
					self._names.setdefault(alias.casefold(), set()).add(path)
		self._headings = {}
		self.edges = tuple((path, target, self.resolve(target.target, source=path, fragment=target.fragment))
			for path, text in self.texts.items() for target in wiki_targets(text))

	@classmethod
	def from_root(cls, root, *, pending=None):
		root = Path(root).expanduser().resolve()
		adapter = SimpleNamespace(NOTE_PATH=str(root), config={"NOTE_NESTED": "all"}, SKIP_DIRECTORIES=_identities._SKIP_DIRECTORIES)
		texts = {}
		for path in _storage.iter_note_files(adapter):
			if path.is_symlink():
				continue
			with path.open(encoding="utf-8", newline="") as stream:
				texts[path.relative_to(root).as_posix()] = stream.read()
		texts.update(pending or {})
		return cls(texts, _identities.load_index(root))

	def _result(self, paths, fragment):
		paths = tuple(sorted(paths))
		if len(paths) != 1:
			return LinkResolution("ambiguous" if paths else "missing", candidates=paths)
		path = paths[0]
		identity = self.identities.get(path)
		heading = None
		if fragment is not None:
			if path not in self._headings:
				text = active_source(self.texts[path])
				from pretty_notebook.markdown import render_notebook
				heading_ids = {heading.identifier for heading in render_notebook(self.texts[path]).headings}
				# Custom/raw HTML headings and wiki text inside headings need an
				# explicit ID before this source-only diagnostic can prove a target.
				unknown = bool(re.search(r"<h[1-6]\b|^ {0,3}#{1,6}[^\n]*\[\[", text, re.I | re.M))
				self._headings[path] = heading_ids, unknown
			known, unknown = self._headings[path]
			heading = "valid" if fragment in known or slugify(fragment, "-") in known else "unknown" if unknown else "missing"
		return LinkResolution("resolved", path, identity.id if identity else None, paths, heading)

	def resolve(self, target, *, source=None, fragment=None):
		"""Root paths first; explicit ./../ paths are relative to the source."""
		target = str(target).strip()
		if target.startswith("[[") and target.endswith("]]"):
			target = target[2:-2].strip()
		address = target.split("|", 1)[0]
		if "#" in address:
			address, inline_fragment = address.split("#", 1)
			fragment = inline_fragment.strip() if fragment is None else fragment
		address = address.strip()
		if not address:
			return self._result({source} if source in self.texts else set(), fragment)
		if address.startswith("id:"):
			path = self._ids.get(address[3:])
			return self._result({path} if path else set(), fragment)
		if "\\" in address or ":" in address or "\x00" in address:
			return LinkResolution("invalid")
		relative = address.startswith(("./", "../"))
		if relative and source not in self.texts:
			return LinkResolution("invalid")
		name = posixpath.normpath(posixpath.join(posixpath.dirname(source), address) if relative else address.lstrip("/"))
		if name in {"..", "."} or name.startswith("../") or any(part in _identities._SKIP_DIRECTORIES for part in name.split("/")):
			return LinkResolution("invalid")
		if name.lower().endswith(".md"):
			name = name[:-3]
		paths = self._paths.get(name.casefold(), set())
		if not paths and not relative and not address.startswith("/") and "/" not in address:
			paths = self._names.get(name.casefold(), set())
		return self._result(paths, fragment)

	def backlinks(self, path):
		return tuple((source, target) for source, target, result in self.edges if result.path == path)

	def diagnostics(self):
		return tuple({"source": source, "line": target.line, "target": target.target,
			"state": result.state, "candidates": list(result.candidates), "heading_state": result.heading_state}
			for source, target, result in self.edges if result.state != "resolved" or result.heading_state in {"missing", "unknown"})
