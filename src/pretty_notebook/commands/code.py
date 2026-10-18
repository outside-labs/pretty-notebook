import json

from collections import defaultdict
from pathlib import Path

from expose_interface import flag, option

from pretty_notebook.models import Note, CodeBlock
from pretty_notebook.helpers import pass_nb


def _code_root(nb):
	"""Return the resolved code directory, rejecting an escaping root symlink."""
	note_root = Path(nb.NOTE_PATH).expanduser().resolve()
	code_root = (note_root / 'code').resolve()

	try:
		code_root.relative_to(note_root)
	except ValueError as error:
		raise ValueError('Code output directory escapes NOTE_PATH.') from error

	return code_root


def _resolve_output_path(code_root, name):
	"""Resolve one relative output beneath the code directory."""
	supplied = Path(name)
	if supplied.is_absolute():
		raise ValueError(f'Cannot use absolute code output path: {name!r}.')

	target = (code_root / supplied).resolve()
	try:
		target.relative_to(code_root)
	except ValueError as error:
		raise ValueError(
			f'Code output path escapes code output directory: {name!r}.'
		) from error

	if target == code_root:
		raise ValueError('Code output path must name a file.')

	return target


def _write_outputs(nb, outputs, *, overwrite=False):
	"""Validate the complete extraction plan, then write it."""
	if not outputs:
		return []

	code_root = _code_root(nb)
	planned = []
	seen = set()

	for name, content in outputs:
		target = _resolve_output_path(code_root, name)
		if target in seen:
			raise ValueError(f'Duplicate code output path: {name!r}.')
		if target.is_dir():
			raise IsADirectoryError(f'Code output path is a directory: {target}')
		if target.exists() and not overwrite:
			raise FileExistsError(
				f'Code output exists: {target}. Pass overwrite=True to replace it.'
			)

		seen.add(target)
		planned.append((target, content))

	code_root.mkdir(parents=True, exist_ok=True)
	written = []
	mode = 'w' if overwrite else 'x'

	for target, content in planned:
		target.parent.mkdir(parents=True, exist_ok=True)
		checked_target = _resolve_output_path(
			code_root,
			target.relative_to(code_root),
		)
		with checked_target.open(mode, encoding='utf-8', newline='') as output_file:
			output_file.write(content)
		written.append(checked_target)

	return written


def _language_and_extension(lang):
	"""Normalize either a configured language or extension to both values."""
	if lang in CodeBlock.LANG_EXTS and CodeBlock.LANG_EXTS[lang]:
		return lang, CodeBlock.LANG_EXTS[lang]

	for language, extension in CodeBlock.LANG_EXTS.items():
		if extension and lang == extension:
			return language, extension

	raise ValueError(
		f'--lang must be any extractable language or extension: '
		f'{json.dumps(CodeBlock.LANG_EXTS, indent=4)}'
	)


def _outputs_for_language(note, lang, extension):
	"""Build output names and verbatim bodies for one language."""
	outputs = []
	unnamed = []

	for codeblock in note.codeblocks:
		if codeblock.lang != lang:
			continue

		if codeblock.fname:
			outputs.append((codeblock.fname, codeblock.extraction_body))
		elif codeblock.body:
			unnamed.append(codeblock.body)

	if unnamed:
		outputs.append((f'{note.name}.{extension}', '\n\n'.join(unnamed)))

	return outputs


@pass_nb
def _collect_code_blocked(nb=None):
	""" if ```lang ``` -> nb/all code blocked.md
	"""
	ns = "\n\n--- \n\n"
	for note in nb.notes.values():
		if any(codeblock.extn for codeblock in note.codeblocks):
			ns += f'[[{note.name}]]\n'

	nb.generate_note('all code blocked', ns, overwrite=True, pnbp=True)


@pass_nb
@flag('--overwrite', help='Replace existing files under NOTE_PATH/code.')
@option('-l', '--lang', help=f'The code language or extension to save: {json.dumps(CodeBlock.LANG_EXTS)}')
def _extract_code_blocks(lang: str, note: Note, overwrite=False, nb=None):
	"""Extract one language, preserving each code body as text."""
	language, extension = _language_and_extension(lang)
	outputs = _outputs_for_language(note, language, extension)
	return _write_outputs(nb, outputs, overwrite=overwrite)


@pass_nb
@flag('--overwrite', help='Replace existing files under NOTE_PATH/code.')
def _extract_all_code_blocks(note: Note, overwrite=False, nb=None):
	"""Extract every supported language, preserving JSON as JSON text."""
	outputs = []
	unnamed = defaultdict(list)

	for codeblock in note.codeblocks:
		if not codeblock.extn:
			continue

		if codeblock.fname:
			outputs.append((codeblock.fname, codeblock.extraction_body))
		elif codeblock.body:
			unnamed[codeblock.extn].append(codeblock.body)

	for extension, bodies in unnamed.items():
		outputs.append((f'{note.name}.{extension}', '\n\n'.join(bodies)))

	return _write_outputs(nb, outputs, overwrite=overwrite)
