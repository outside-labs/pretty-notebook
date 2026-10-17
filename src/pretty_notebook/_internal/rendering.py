"""Production rendering dispatch and reproducible backend fingerprints."""

from pathlib import Path

from pretty_notebook.markdown import RendererContext, render_notebook


def render_note(notebook, note):
    """Render pending source without changing the note's staged state."""
    backend = notebook.config.get('MARKDOWN_BACKEND', 'typed')
    if backend == 'python-markdown':
        from .legacy_rendering import render_note as legacy_render
        return legacy_render(notebook, note)
    if backend != 'typed':
        raise ValueError('Unknown Markdown backend.')
    return render_notebook(note.current_md, context=RendererContext(
        notebook, note.source_path, trust='trusted', dialect='notebook',
    )).html


def backend_identity(notebook):
    """Return all implementation inputs that can change rendered publication HTML."""
    from pretty_notebook import markdown
    backend = notebook.config.get('MARKDOWN_BACKEND', 'typed')
    directory = Path(markdown.__file__).parent
    files = [Path(__file__), *sorted(directory.glob('*.py'))]
    identity = {'backend': backend, 'dialect': 'notebook-1'}
    if backend == 'python-markdown':
        from importlib.metadata import PackageNotFoundError, version
        try:
            identity['legacy_version'] = version('Markdown')
        except PackageNotFoundError as error:
            raise RuntimeError('The python-markdown backend requires pretty-notebook[legacy-markdown].') from error
        files.append(Path(__file__).with_name('legacy_rendering.py'))
    import hashlib
    identity['implementation'] = hashlib.sha256(b''.join(file.name.encode() + b'\0' + file.read_bytes() for file in files)).hexdigest()
    return identity
