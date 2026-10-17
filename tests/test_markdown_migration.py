import json
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pretty_notebook import Notebook, NotebookSettings, SettingsError
from pretty_notebook._internal import publication_plan
from pretty_notebook._internal.legacy_rendering import render_note as legacy_render
from pretty_notebook.markdown import RendererContext, parse_notebook, render_notebook


class _Html(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        self.events.append(('start', tag, tuple(sorted(attrs))))
        if tag not in {'br', 'hr', 'img', 'input', 'meta', 'link', 'area', 'wbr'}:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.events.append(('end', tag))
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if not data.strip() and (not self.stack or self.stack[-1] in {'div', 'ul', 'ol', 'table', 'thead', 'tbody', 'tr', 'svg'}):
            return
        self.events.append(('text', data))

    def handle_comment(self, data):
        self.events.append(('comment', data))


def canonical(source):
    parser = _Html()
    parser.feed(source)
    # Entity boundaries can split adjacent text callbacks without changing HTML.
    values = []
    for event in parser.events:
        if values and values[-1][0] == event[0] == 'text':
            values[-1] = ('text', values[-1][1] + event[1])
        else:
            values.append(event)
    return values


CASES = [
    ('headings', '# One\n\nTwo\n---\n\n## Repeat\n## Repeat\n', ''),
    ('heading-attrs', '# One {#custom .sample}\n', 'consistent-heading-attributes'),
    ('formatting', '**bold** and *emphasis*\n~~strike~~ ==mark==\n', ''),
    ('paragraphs', 'one\ntwo\n\nthree\n', ''),
    ('unordered', '- one\n- two\n', ''),
    ('ordered', '1. first\n2. second\n', ''),
    ('mixed-lists', '- one\n- two\n\n1. first\n2. second\n', 'commonmark-list-types'),
    ('quotes', '> quote\n> continuation\n', ''),
    ('table', '| A | B |\n| :--- | ---: |\n| x | y |\n', ''),
    ('footnotes', 'Text[^a] again[^a].\n\n[^a]: A **footnote**.\n', ''),
    ('toc', '# Heading\n\n[TOC]\n', 'local-toc-links'),
    ('wiki', '[[Target#Section|Label]] [[missing|fallback]] ![[image.png]]\n', ''),
    ('url', 'See https://example.com/path and [site](https://example.org).\n', ''),
    ('code', '```{.python #sample}\n\t[[Target]] #tag ~~x~~ ==y== <b>&\n\n```\n', ''),
    ('inline-code', 'Literal `[[Target]] #tag ~~x~~ ==y==`\n', ''),
    ('mermaid', '```mermaid\ngraph TD\nA["<script>"] --> B\n```\n', ''),
    ('raw-html', '<div class="custom">Trusted <b>HTML</b>.</div>\n', ''),
    ('ordered-start', '3. third\n4. fourth\n', 'commonmark-list-start'),
    ('nested-lists', '- outer\n  - nested\n', 'commonmark-list-indentation'),
    ('unsafe-url', '[unsafe](javascript:alert)\n', 'restricted-url-policy'),
    ('titled-link', '[site](https://example.com "Title")\n', 'consistent-link-decoration'),
    ('indented-literal', '    [[Target]] #tag ~~literal~~\n', 'protected-indented-code'),
    ('raw-literal', '<pre>[[Target]] #tag ~~literal~~</pre>\n', 'protected-html-code'),
    ('inline-html-literal', 'Before <code>[[Target]] ~~literal~~</code> after\n', 'protected-html-code'),
    ('escaped-wiki', '\\[[Target]]\n', 'escaped-wiki-link'),
]


@pytest.fixture
def notebook(monkeypatch, tmp_path):
    monkeypatch.setenv('PNBP_SETTINGS', 'off')
    monkeypatch.delenv('MARKDOWN_BACKEND', raising=False)
    (tmp_path / 'Target.md').write_text('#public\n# Section\n')
    (tmp_path / 'Source.md').write_text('Original.\n')
    return Notebook(tmp_path)


@pytest.mark.parametrize('name,source,difference', CASES, ids=[row[0] for row in CASES])
def test_differential_notebook_contract(notebook, name, source, difference):
    pytest.importorskip('markdown')
    note = notebook.notes['Source']
    note.md_out = source
    previous = note.md_out
    legacy = legacy_render(notebook, note)
    typed = notebook.convert_to_html(note)
    if difference:
        assert canonical(typed) != canonical(legacy), difference
    else:
        assert canonical(typed) == canonical(legacy)
    assert note.md_out == previous and note.md == 'Original.\n'
    assert parse_notebook(source).to_markdown() == source


def test_backend_setting_is_explicit_and_validated(notebook):
    pytest.importorskip('markdown')
    assert NotebookSettings().markdown_backend == 'typed'
    legacy = Notebook(notebook.NOTE_PATH, settings={'MARKDOWN_BACKEND': 'python-markdown'})
    assert legacy.convert_to_html(legacy.notes['Source']) == legacy_render(legacy, legacy.notes['Source'])
    for value in ['unknown', True, 42]:
        with pytest.raises(SettingsError, match='MARKDOWN_BACKEND'):
            Notebook(notebook.NOTE_PATH, settings={'MARKDOWN_BACKEND': value})


def test_anchors_match_note_navigation_and_graph_resolution(notebook):
    note = notebook.notes['Source']
    note.md_out = '# Héading\n## Again\n## Again\n## Explicit {#read}\n'
    rendered = notebook.convert_to_html(note)
    outline = notebook.navigation_index().outline(note)
    expected = [item.identifier for item in render_notebook(note.current_md).headings]
    assert [item.anchor for item in outline] == expected
    for anchor in expected:
        assert f'id="{anchor}"' in rendered
        assert notebook.graph_index().resolve('Source#' + anchor).heading_state == 'valid'


def test_backend_and_implementation_are_bound_to_publication_plans(notebook, monkeypatch):
    initial = publication_plan.renderer_fingerprint(notebook)
    notebook.config['MARKDOWN_BACKEND'] = 'python-markdown'
    pytest.importorskip('markdown')
    assert publication_plan.renderer_fingerprint(notebook) != initial
    notebook.config['MARKDOWN_BACKEND'] = 'typed'
    from pretty_notebook._internal import rendering
    original = rendering.backend_identity
    monkeypatch.setattr(rendering, 'backend_identity', lambda nb: {**original(nb), 'implementation': 'changed'})
    assert publication_plan.renderer_fingerprint(notebook) != initial


def test_render_navigation_graph_and_plans_do_not_import_python_markdown(tmp_path):
    program = r'''
import importlib.abc
import sys
from pathlib import Path
class BlockMarkdown(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'markdown':
            raise ModuleNotFoundError('Python-Markdown deliberately unavailable', name='markdown')
sys.meta_path.insert(0, BlockMarkdown())
from pretty_notebook import Notebook
from pretty_notebook.markdown import Document, Paragraph, PythonMarkdownRenderer
from pretty_notebook._internal.publication_plan import renderer_fingerprint
root = Path(sys.argv[1])
(root / 'note.md').write_text('# Heading\n\n**bold** [[#Heading]]\n')
nb = Notebook(root)
assert '<strong>bold</strong>' in nb.convert_to_html(nb.notes['note'])
assert nb.navigation_index().outline('note')[0].anchor == 'heading'
assert nb.graph_index().resolve('note#heading').heading_state == 'valid'
assert len(renderer_fingerprint(nb)) == 64
assert Document(Paragraph('builder')).to_html() == '<p>builder</p>'
assert 'markdown' not in sys.modules
for operation in [lambda: Document(Paragraph('x')).to_html(renderer=PythonMarkdownRenderer()),
                  lambda: Notebook(root, settings={'MARKDOWN_BACKEND':'python-markdown'}).convert_to_html(nb.notes['note'])]:
    try:
        operation()
    except RuntimeError as error:
        assert 'legacy-markdown' in str(error)
    else:
        raise AssertionError('Missing optional dependency should be explained')
'''
    subprocess.run([sys.executable, '-c', program, str(tmp_path)], check=True,
                   env={**os.environ, 'PNBP_SETTINGS': 'off', 'MARKDOWN_BACKEND': 'typed'})


def test_render_failure_keeps_pending_state(notebook):
    from pretty_notebook.markdown import ParseLimitError
    note = notebook.notes['Source']
    note.md_out = 'x' * 2_000_001
    with pytest.raises(ParseLimitError, match='character limit'):
        notebook.convert_to_html(note)
    assert note.md_out == 'x' * 2_000_001 and note.md == 'Original.\n'
