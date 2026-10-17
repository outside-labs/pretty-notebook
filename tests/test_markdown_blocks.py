import json
from dataclasses import FrozenInstanceError
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pretty_notebook.markdown import (
    BlockQuote, BulletList, CodeBlock, Document, Heading, ListItem, OrderedList,
    Paragraph, ParseLimitError, ParseOptions, Text, ThematicBreak, parse_blocks,
)


CASES = json.loads((Path(__file__).parent / 'fixtures/markdown/commonmark-blocks.json').read_text())


def _tree_events(node, tight=False):
    if isinstance(node, Text) or type(node).__name__ in {'RawHtml', 'ReferenceDefinition'}:
        return []
    if isinstance(node, CodeBlock):
        return [('start', 'pre'), ('code', node.body), ('end', 'pre')]
    if isinstance(node, ThematicBreak):
        return [('start', 'hr')]
    if isinstance(node, Heading):
        name = f'h{node.level}'
    elif isinstance(node, BlockQuote):
        name = 'blockquote'
    elif isinstance(node, OrderedList):
        name = 'ol'
    elif isinstance(node, BulletList):
        name = 'ul'
    elif isinstance(node, ListItem):
        name = 'li'
    elif isinstance(node, Paragraph):
        name = None if tight else 'p'
    elif isinstance(node, Document):
        name = None
    else:
        raise AssertionError(type(node))
    inside = node.tight if isinstance(node, BulletList) else tight if isinstance(node, ListItem) else False
    events = [event for child in node.children for event in _tree_events(child, inside)]
    return ([('start', name)] + events + [('end', name)]) if name else events


class _HtmlEvents(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events, self.code = [], None

    def handle_starttag(self, tag, attrs):
        if tag == 'code' and self.code is not None:
            return
        if tag in {'p', 'pre', 'blockquote', 'ul', 'ol', 'li', 'hr', *('h' + str(i) for i in range(1, 7))}:
            self.events.append(('start', tag))
        if tag == 'pre':
            self.code = ''

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.events.append(('code', self.code))
            self.code = None
        if tag in {'p', 'pre', 'blockquote', 'ul', 'ol', 'li', *('h' + str(i) for i in range(1, 7))}:
            self.events.append(('end', tag))

    def handle_data(self, data):
        if self.code is not None:
            self.code += data


@pytest.mark.parametrize('case', CASES, ids=lambda c: f"{c['section']}-{c['example']}")
def test_official_block_structure(case):
    expected = _HtmlEvents()
    expected.feed(case['html'])
    document = parse_blocks(case['markdown'])
    assert document.to_markdown() == case['markdown']
    assert _tree_events(document) == expected.events


def _walk(node):
    yield node
    for child in getattr(node, 'children', ()):
        yield from _walk(child)


@pytest.mark.parametrize('ending', ['\n', '\r\n', '\r'])
def test_exact_source_and_nested_code_point_spans(ending):
    source = ending.join(['# ☃', '', '> - nested', '>   continuation', '', '```py', '\t☃', '```', ''])
    document = parse_blocks(source)
    assert document.to_markdown() == source
    for node in _walk(document):
        assert 0 <= node.span.start <= node.span.end <= len(source)
        assert node.to_markdown() == source[node.span.start:node.span.end]
    assert document.children[1].span.start_line == 3
    assert document.children[0].children[0].span.start_column == 3
    assert document.children[2].body == '\t☃\n'
    with pytest.raises(FrozenInstanceError):
        document.source = 'changed'


def test_incomplete_fence_has_diagnostic_and_literal_body():
    document = parse_blocks('```py\n[[link]] #tag\n')
    assert document.children[0].body == '[[link]] #tag\n'
    assert document.diagnostics[0].code == 'unclosed-fence'
    assert document.diagnostics[0].span.end == len(document.source)


@pytest.mark.parametrize('source,options,code', [
    ('x' * 101, ParseOptions(max_characters=100), 'character-limit'),
    ('> ' * 6 + 'text', ParseOptions(max_nesting=5), 'nesting-limit'),
    ('a\n\nb\n\nc', ParseOptions(max_nodes=5), 'node-limit'),
])
def test_limits_fail_without_partial_output(source, options, code):
    with pytest.raises(ParseLimitError) as error:
        parse_blocks(source, options=options)
    assert error.value.diagnostic.code == code


def test_long_input_and_unknown_syntax_stay_source_preserving():
    source = ('ordinary ' * 10_000) + '\n\n::: unknown syntax\n'
    document = parse_blocks(source)
    assert document.to_markdown() == source and len(document.children) == 2


def test_parsing_pending_markdown_does_not_mutate_a_note(monkeypatch, tmp_path):
    from pretty_notebook import Notebook
    monkeypatch.setenv('PNBP_SETTINGS', 'off')
    monkeypatch.setenv('NOTE_PATH', str(tmp_path))
    (tmp_path / 'note.md').write_text('Original.\n')
    note = Notebook().notes['note']
    note.md_out = '# Pending\r\n'
    assert parse_blocks(note.current_md).to_markdown() == note.md_out
    assert note.md == 'Original.\n' and note.md_out == '# Pending\r\n'
    assert (tmp_path / 'note.md').read_text() == 'Original.\n'
