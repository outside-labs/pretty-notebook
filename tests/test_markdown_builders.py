import html
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from pretty_notebook.markdown import (
    BoldText, BulletList, CodeBlock, Document, Heading, Image, ItalicText,
    Link, ListItem, MarkdownText, OrderedList, Paragraph, RendererContext,
    Text, from_component,
)
from pretty_notebook.models import components


def test_nested_builders_are_deterministic_and_immutable():
    document = Document(Heading(2, 'Example'), Paragraph('A ', BoldText('bold ', ItalicText('word'))),
                        BulletList('one', ListItem(Paragraph('two'), OrderedList('nested'))))
    assert document.to_markdown() == '## Example\n\nA **bold *word***\n\n- one\n- two\n\n    1. nested'
    assert document.to_html() == document.to_html()
    assert '<strong>bold <em>word</em></strong>' in document.to_html()
    assert '<ul>' in document.to_html() and '<ol>' in document.to_html()
    assert MarkdownText is Document
    with pytest.raises(FrozenInstanceError):
        document.children = ()


def test_text_is_literal_even_at_block_boundaries():
    text = '    # Heading\n<script>alert(1)</script> **bold** &amp; [x](javascript:bad)'
    rendered = Document(Paragraph(text)).to_html()
    assert html.unescape(rendered) == '<p>' + text + '</p>'
    assert '<script>' not in rendered and '<strong>' not in rendered and '<a ' not in rendered


def test_links_images_titles_and_code_are_escaped():
    document = Document(Paragraph(Link('https://example.com/a(b)', 'a [label]', title='a "title"'),
                                  Image('/image.png', '<alt>', title='"')),
                        CodeBlock('```\n<script>&\n', 'python'))
    rendered = document.to_html()
    assert 'href="https://example.com/a%28b%29"' in rendered
    assert 'title="a &quot;title&quot;"' in rendered
    assert 'alt="<alt>"' in html.unescape(rendered)
    assert '&lt;script&gt;&amp;' in rendered
    assert document.to_markdown().endswith('````')


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'javascript&#58;alert(1)', 'data:text/html,a', 'java%73cript:x', '//evil.example', 'https://ok/\nx', 'a\\b'])
def test_unsafe_builder_destinations_are_rejected(url):
    with pytest.raises(ValueError):
        Link(url, 'text')
    with pytest.raises(ValueError):
        Image(url)


@pytest.mark.parametrize('factory', [lambda: Heading(True, 'a'), lambda: Heading(7, 'a'),
                                    lambda: OrderedList('a', start=-1), lambda: Paragraph(42),
                                    lambda: CodeBlock('body', 'py\ninjected'), lambda: RendererContext(trust='other')])
def test_invalid_builder_inputs_fail_early(factory):
    with pytest.raises((ValueError, TypeError)):
        factory()


def test_legacy_components_remain_strings_and_have_explicit_adapters(monkeypatch, tmp_path):
    from pretty_notebook import Notebook
    monkeypatch.setenv('PNBP_SETTINGS', 'off')
    monkeypatch.setenv('NOTE_PATH', str(tmp_path))
    (tmp_path / 'Target.md').write_text('Target.\n')
    link = components.Link(link='Target|Label')
    assert link == 'Target|Label' and hash(link) == hash('Target|Label')
    assert from_component(link).to_markdown() == '[[Target|Label]]'
    assert 'href="/target"' in Document(Paragraph(from_component(link))).to_html(context=RendererContext(Notebook()))
    assert from_component(components.Tag('#tag')) == Text('#tag')
    assert from_component(components.Url('https://example.com')).destination == 'https://example.com'
    assert from_component(components.CodeBlock('py\nprint(1)\n')) == CodeBlock('print(1)\n', 'py')
    with pytest.raises(TypeError):
        from_component('plain')


def test_renderer_protocol_receives_the_same_document_and_context():
    document, context = Document(Paragraph('hello')), RendererContext()
    class CustomRenderer:
        def render(self, node, inputs):
            assert node is document and inputs is context
            return 'custom'
    assert document.to_html(renderer=CustomRenderer(), context=context) == 'custom'


def test_import_does_not_load_web_or_validation_frameworks():
    subprocess.run([sys.executable, '-c',
                    'import sys; import pretty_notebook.markdown; '
                    'assert not {"fastapi", "pydantic", "uvicorn"}.intersection(sys.modules)'], check=True)
