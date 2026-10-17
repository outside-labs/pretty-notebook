import html

import pytest

from pretty_notebook.markdown import (
    FootnoteDefinition, ImageEmbed, Mermaid, NotebookLink, RendererContext,
    StrikethroughText, Table, TagText, TaskListItem, parse, parse_notebook, render_notebook,
)


def _walk(node):
    yield node
    for child in getattr(node, 'children', ()):
        yield from _walk(child)


def test_dialect_is_explicit_and_preserves_original_source():
    source = '# Heading {#custom}\r\n\r\n~~one~~ ==two== [[wiki]] ![[image.png]] #topic\r\n'
    document = parse_notebook(source)
    assert document.to_markdown() == source
    kinds = {type(node) for node in _walk(document)}
    assert {StrikethroughText, NotebookLink, ImageEmbed, TagText} <= kinds
    assert '<s>' not in parse(source).to_html()
    assert render_notebook(source).headings[0].identifier == 'custom'


def test_nested_formatting_and_comparisons():
    rendered = render_notebook('~~one **strong**~~ and ~~two~~\n==three *em*== and ==four==\nplain x == y == z').html
    assert '<s>one <strong>strong</strong></s> and <s>two</s>' in rendered
    assert '<mark>three <em>em</em></mark> and <mark>four</mark>' in rendered
    assert 'plain x == y == z' in rendered


def test_tables_alignment_escaped_pipes_padding_and_inline_code():
    source = '| A | B |\n| :--- | ---: |\n| a\\|b | `x|y` |\n| only |\n'
    document = parse_notebook(source)
    assert isinstance(document.children[0], Table)
    rendered = document.to_html()
    assert '<th style="text-align: left;">A</th>' in rendered
    assert '<td style="text-align: right;"><code>x|y</code></td>' in rendered
    assert 'a|b' in rendered and '<td style="text-align: right;"></td>' in rendered
    assert document.to_markdown() == source


def test_nested_tasks_have_typed_state_and_disabled_checkboxes():
    source = '- [ ] first\n  - [x] nested\n- [X] done\n'
    document = parse_notebook(source)
    tasks = [node for node in _walk(document) if isinstance(node, TaskListItem)]
    assert [task.checked for task in tasks] == [False, True, True]
    rendered = document.to_html()
    assert rendered.count('disabled=""') == 3 and rendered.count('checked=""') == 2
    assert document.to_markdown() == source


def test_footnotes_have_multiple_backlinks_and_block_content():
    source = 'Text[^one] again[^one] and [^missing].\n\n[^one]: A **footnote**.\n\n    Another paragraph.\n'
    document = parse_notebook(source)
    assert isinstance(document.children[1], FootnoteDefinition)
    rendered = document.to_html()
    assert 'id="fnref:one"' in rendered and 'id="fnref2:one"' in rendered
    assert rendered.count('class="footnote-backref"') == 2
    assert '<p>Another paragraph.' in rendered and '[^missing]' in rendered
    assert document.to_markdown() == source


def test_attributes_heading_ids_toc_and_metadata_share_anchors():
    source = '# Héading\n## Repeat\n## Repeat\n## Custom {: #read .chapter onclick="bad"}\n\n[TOC]\n\n[link](/safe){: .reference title="A &quot; title"}\n'
    result = render_notebook(source)
    assert [heading.identifier for heading in result.headings] == ['heading', 'repeat', 'repeat_1', 'read']
    for heading in result.headings:
        assert f'id="{heading.identifier}"' in result.html
        assert f'href="#{heading.identifier}"' in result.html
    assert 'onclick' not in result.html and 'class="chapter"' in result.html
    assert 'class="reference"' in result.html and 'title="A &quot; title"' in result.html


def test_attributes_cannot_inject_attributes_or_executable_urls():
    source = '## Safe {#safe onmouseover="bad" style="color:red"}\n\n![alt](javascript:bad){: onerror="bad" data-label="&quot;"}\n'
    rendered = render_notebook(source).html
    assert 'onmouseover=' not in rendered and 'onerror=' not in rendered and 'style=' not in rendered
    assert 'src=""' in rendered and 'data-label="&quot;"' in rendered


def test_mermaid_and_code_metadata_are_structured_and_literal():
    body = '\t[[wiki]] #tag <script> ==literal==\n'
    source = f'```mermaid\n{body}```\n\n```{{.python #sample .extra}}\nprint(1)\n```\n'
    document = parse_notebook(source)
    assert isinstance(document.children[0], Mermaid)
    result = render_notebook(source)
    assert result.languages == ('mermaid', 'python')
    assert result.diagrams[0].source == body
    assert '<pre class="mermaid">' in result.html and '<script>' not in result.html
    assert '<pre class="extra" id="sample"><code class="language-python">' in result.html
    assert body in html.unescape(result.html)


@pytest.fixture
def notebook(tmp_path, monkeypatch):
    from pretty_notebook import Notebook
    monkeypatch.setenv('PNBP_SETTINGS', 'off')
    monkeypatch.setenv('NOTE_PATH', str(tmp_path))
    (tmp_path / 'Target.md').write_text('#public\n# Section\n')
    (tmp_path / 'Source.md').write_text('Source\n')
    return Notebook()


def test_wiki_resolution_prefix_fragments_labels_and_images_use_notebook(notebook, monkeypatch):
    notebook.config['URL_PREFIX'] = '/notes'
    calls = []
    original = notebook.graph_index
    def graph():
        calls.append(True)
        return original()
    monkeypatch.setattr(notebook, 'graph_index', graph)
    result = render_notebook('[[Target#Section|<label>]] [[Target|other]] [[#Section]] [[missing|fallback]] ![[☃.png]]', context=RendererContext(notebook, 'Source.md'))
    assert "href='/notes/target#section'" in result.html
    assert '&lt;label&gt;' in result.html and ' fallback ' in result.html
    assert "href='#section'" in result.html and '/notes/static/imgs/%E2%98%83.png' in result.html
    assert len(calls) == 1


@pytest.mark.parametrize('literal', [
    '`[[Target]] #public ~~strike~~ ==mark== https://example.com`',
    '```text\n[[Target]] #public ~~strike~~ ==mark== https://example.com\n```',
    '    [[Target]] #public ~~strike~~ ==mark== https://example.com\n',
    '```mermaid\n[[Target]] #public ~~strike~~ ==mark== https://example.com\n```',
    '<pre>[[Target]] #public ~~strike~~ ==mark== https://example.com</pre>',
])
def test_extensions_leave_protected_text_opaque(literal, notebook):
    result = render_notebook(literal, context=RendererContext(notebook, 'Source.md', trust='trusted'))
    assert '<a ' not in result.html and '<s>' not in result.html and '<mark>' not in result.html
    assert '[[Target]] #public ~~strike~~ ==mark== https://example.com' in html.unescape(result.html)


def test_newlines_and_hidden_commit_tags_follow_the_notebook_policy(notebook):
    notebook.config['HIDE_COMMIT_TAG'] = True
    source = '#public #topic\nsecond `#public`\n'
    result = render_notebook(source, context=RendererContext(notebook, 'Source.md'))
    assert '<br />\n' in result.html and '<code>#public</code>' in result.html
    assert result.html.count('#public') == 1 and '#topic' in result.html
    assert '<br' not in render_notebook(source, context=RendererContext(soft_breaks='newline')).html
