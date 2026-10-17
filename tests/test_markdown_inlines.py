import html
import json
import re
from pathlib import Path

import pytest

from pretty_notebook.markdown import (
    Code, Link, ParseLimitError, ParseOptions, RendererContext, Text, TypedRenderer, parse,
)
from pretty_notebook.markdown.nodes import safe_url

CASES = json.loads((Path(__file__).parent / 'fixtures/markdown/commonmark-inlines.json').read_text())


def _policy_urls(source, document):
    def unsafe(node):
        if isinstance(node, Link) or type(node).__name__ == 'Image':
            try:
                safe_url(node.destination)
            except ValueError:
                return True
        return any(unsafe(child) for child in getattr(node, 'children', ()))
    if not unsafe(document):
        return source
    def attribute(match):
        try:
            safe_url(html.unescape(match[2]))
            return match[0]
        except ValueError:
            return match[1] + '=""'
    return re.sub(r'(href|src)="([^"]*)"', attribute, source)


@pytest.mark.parametrize('case', CASES, ids=lambda c: f"{c['section']}-{c['example']}")
def test_official_inline_rendering(case):
    document = parse(case['markdown'])
    expected = case['html'] if case['section'] == 'Raw HTML' else _policy_urls(case['html'], document)
    assert document.to_markdown() == case['markdown']
    assert document.to_html(context=RendererContext(trust='trusted')) == expected.removesuffix('\n')


def test_default_policy_escapes_html_and_disables_unsafe_destinations():
    rendered = parse('<script>alert(1)</script>\n\n[x](javascript:alert(1)) ![x](data:text/html,bad)\n').to_html()
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert 'href=""' in rendered and 'src=""' in rendered
    assert 'javascript:' not in rendered and 'data:' not in rendered


def test_entities_and_escapes_cannot_change_link_scheme_or_attributes():
    rendered = parse('[x](javascript&#58;alert) [x](java%73cript:bad) ![" onerror="x](/safe "a &quot; b")').to_html()
    assert rendered.count('href=""') == 2
    assert 'alt="&quot; onerror=&quot;x"' in rendered
    assert 'title="a &quot; b"' in rendered


def test_nested_nodes_map_around_quote_prefixes():
    source = '> **bold\n> *emphasis* and `code`**\r\n'
    document = parse(source)
    strong = document.children[0].children[0].children[0]
    assert strong.to_markdown() == '**bold\n> *emphasis* and `code`**'
    assert strong.span.start_column == 3 and strong.span.end_line == 2
    assert 'emphasis' in document.to_html()


def test_inline_limits_and_long_unmatched_delimiters_are_bounded():
    assert 'a' * 100_000 in parse('a' * 100_000).to_html()
    assert parse('a ' + '`' * 100_000).children[0].children[-1].value == '`' * 100_000
    with pytest.raises(ParseLimitError):
        parse('*a ' * 100, options=ParseOptions(max_nodes=30))


def test_native_renderer_also_accepts_builder_nodes():
    from pretty_notebook.markdown import Document, Paragraph
    assert Document(Paragraph(Text('<safe>'), Code('x < y'), Link('/safe', 'label'))).to_html(renderer=TypedRenderer()) == '<p>&lt;safe&gt;<code>x &lt; y</code><a href="/safe">label</a></p>'


@pytest.mark.parametrize('case', json.loads((Path(__file__).parent / 'fixtures/markdown/commonmark-blocks.json').read_text()), ids=lambda c: f"block-render-{c['example']}")
def test_block_cases_with_native_inline_rendering(case):
    document = parse(case['markdown'])
    assert document.to_html(context=RendererContext(trust='trusted')) == _policy_urls(case['html'], document).removesuffix('\n')


def test_raw_html_builders_obey_both_renderer_policies():
    from pretty_notebook.markdown import Document, Paragraph, RawHtml, PythonMarkdownRenderer
    for renderer in (PythonMarkdownRenderer(), TypedRenderer()):
        assert '<script>' not in Document(Paragraph(RawHtml('<script>'))).to_html(renderer=renderer)
        assert '<script>' in Document(Paragraph(RawHtml('<script>'))).to_html(renderer=renderer, context=RendererContext(trust='trusted'))


@pytest.mark.parametrize('source', ['[label](/target) ' * 2000, 'a `code` ' * 5000, '*word* ' * 5000], ids=['links', 'code', 'emphasis'])
def test_representative_long_inlines(source):
    assert parse(source).to_markdown() == source



def test_escaped_backtick_can_leave_a_shorter_unmatched_run():
    assert parse('a \\``` b').to_html() == '<p>a ``` b</p>'
