"""Optional Python-Markdown compatibility renderer and literal protection pipeline."""

import re
from html import escape
from urllib.parse import quote
from pretty_notebook.markdown.dialect import slugify
from pretty_notebook._internal import routes as _routes
from pretty_notebook.models.components import Link, Tag, Url

_FENCED_LITERAL = re.compile(
	r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n"
	r"(?P<body>.*?)"
	r"^(?P=indent)(?P=fence)[ \t]*(?:\n|$)",
	re.MULTILINE | re.DOTALL,
)
_INLINE_LITERAL = re.compile(
	r"(?<!`)(?P<fence>`+)(?!`)(?P<body>.+?)(?P=fence)(?!`)",
	re.DOTALL,
)
_HTML_LITERAL = re.compile(
	r"<div class=(?:\"|')mermaid(?:\"|')[^>]*>.*?</div>"
	r"|<pre\b[^>]*>.*?</pre>"
	r"|<code\b[^>]*>.*?</code>",
	re.IGNORECASE | re.DOTALL,
)


def _stash_literal(text, stashed, value):
	index = len(stashed)
	token = f"PNBPLITERAL{index}TOKEN"
	while token in text or token in stashed:
		index += 1
		token = f"PNBPLITERAL{index}TOKEN"
	stashed[token] = value
	return token


def _stash_markdown_literals(text):
	stashed = {}
	code_bodies = {}

	def stash_fence(match):
		info = match.group("info").strip().split()
		index = len(code_bodies)
		token = f"PNBPCODEBODY{index}TOKEN"
		while token in text or token in code_bodies or token + "\n" in code_bodies:
			index += 1
			token = f"PNBPCODEBODY{index}TOKEN"
		if info and info[0].lower() == "mermaid":
			code_bodies[token] = escape(match.group("body"))
			replacement = f'<pre class="mermaid">{token}</pre>'
			if match.group(0).endswith("\n"):
				replacement += "\n"
		else:
			# Let Markdown render fence attributes, but keep its whitespace
			# normalization away from the original code (including tabs).
			code_bodies[token + "\n"] = escape(match.group("body"))
			code_bodies[token] = escape(match.group("body"))
			start = match.start("body") - match.start()
			end = match.end("body") - match.start()
			indent = match.group("indent")
			opening = match.group(0)[:start].removeprefix(indent)
			closing = match.group(0)[end:].removeprefix(indent)
			replacement = opening + token + "\n" + closing
		return _stash_literal(text, stashed, replacement)

	protected = _FENCED_LITERAL.sub(stash_fence, text)

	def stash_inline(match):
		return _stash_literal(text, stashed, match.group(0))

	protected = _INLINE_LITERAL.sub(stash_inline, protected)
	return protected, stashed, code_bodies


def _stash_html_literals(text):
	stashed = {}

	def stash(match):
		return _stash_literal(text, stashed, match.group(0))

	return _HTML_LITERAL.sub(stash, text), stashed


def _restore_literals(text, stashed):
	for token, literal in stashed.items():
		text = text.replace(token, literal)
	return text


def render_note(notebook, note):
	try:
		import markdown as md
	except ModuleNotFoundError as error:
		raise RuntimeError("The python-markdown backend requires pretty-notebook[legacy-markdown].") from error

	"""Render one note while keeping literal code spans opaque to extensions.

	:param note: a Note instance
	"""
	previous_md_out = note.md_out

	try:
		note.md_out, markdown_literals, code_bodies = _stash_markdown_literals(note.current_md)

		if notebook.PUB_LNK_ONLY:
			note = notebook.remove_nonpub_links(note)

		if notebook.config.get('HIDE_COMMIT_TAG') == True:
			note = notebook.hide_commit_tag(note)

		prefix = notebook.config.get("URL_PREFIX", "")
		graph = notebook.graph_index()
		notes_by_path = {n.source_path: n for n in notebook.notes.values()}

		def image(match):
			name = match.group(1).strip()
			url = _routes.public_image_url(notebook.config, name)
			return f"<img class=\"img-fluid\" src='{escape(url, quote=True)}'>"

		def link(match):
			address, _, label = match.group(1).partition("|")
			target, separator, heading = address.partition("#")
			label = label.strip() or address.strip().replace("#", " > ")
			if not target.strip() and separator:
				url = ""
			else:
				resolved = graph.resolve(address, source=note.source_path)
				linked = notes_by_path.get(resolved.path)
				if resolved.state != "resolved" or linked is None:
					return escape(label)
				url = _routes.public_url(prefix, _routes.route_for(linked, notebook.config).route)
			if separator:
				url += "#" + quote(slugify(heading.strip(), "-"))
			return f"<a href='{escape(url, quote=True)}'>{escape(label)}</a>"

		note.md_out = re.sub(Link.MDS_IMG_LNK, image, note.md_out)
		note.md_out = re.sub(Link.MDS_INT_LNK, link, note.md_out)
		nout = note
		nout = Tag.replace_smdtags(nout)
		nout = Url.replace_nakedhref(nout)

		nout.md_out = _restore_literals(nout.md_out, markdown_literals)
		nout.md_out = md.markdown(
			nout.md_out,
			extensions=[
				'fenced_code',
				'nl2br',
				'markdown.extensions.tables',
				'attr_list',
				'footnotes',
				'toc',
			],
			use_pygments=True,
		)
		nout.md_out = _restore_literals(nout.md_out, code_bodies)

		nout.md_out, html_literals = _stash_html_literals(nout.md_out)
		nout = notebook.replace_strikethrough(nout)
		nout = notebook.replace_eqhighlight(nout)
		nout = Url.adjust_externallinks(nout)
		nout.md_out = _restore_literals(nout.md_out, html_literals)

		return nout.md_out

	finally:
		note.md_out = previous_md_out
