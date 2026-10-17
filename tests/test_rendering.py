import html
import re

import pytest

from pretty_notebook import Notebook


@pytest.fixture(params=['legacy', 'typed'])
def notebook(monkeypatch, tmp_path, request):
	if request.param == 'legacy':
		pytest.importorskip('markdown')
		from pretty_notebook._internal import rendering, legacy_rendering
		monkeypatch.setattr(rendering, 'render_note', legacy_rendering.render_note)
	if request.param == 'typed':
		from pretty_notebook._internal import rendering
		from pretty_notebook.markdown import render_notebook, RendererContext
		monkeypatch.setattr(rendering, 'render_note', lambda nb, note: render_notebook(note.current_md, context=RendererContext(nb, note.source_path, trust='trusted')).html)
	monkeypatch.setenv("NOTE_PATH", str(tmp_path))
	monkeypatch.setenv("PNBP_SETTINGS", "off")
	(tmp_path / "other.md").write_text("Other.\n", encoding="utf-8")
	return tmp_path


def _code_fragments(rendered):
	return [
		html.unescape(fragment)
		for fragment in re.findall(r"<code[^>]*>(.*?)</code>", rendered, flags=re.DOTALL)
	]


def test_fenced_code_keeps_wikilinks_and_comments_literal(notebook):
	source = (
		"Normal [[other]].\n\n"
		"```text\n[[other]]\n```\n\n"
		"```python\n# comment\n```\n"
	)
	(notebook / "alpha.md").write_text(source, encoding="utf-8")
	nb = Notebook()

	rendered = nb.convert_to_html(nb.notes["alpha"])
	fragments = _code_fragments(rendered)

	assert rendered.count("href='/other'") == 1
	assert any("[[other]]" in fragment for fragment in fragments)
	assert any("# comment" in fragment for fragment in fragments)
	assert all("<a " not in fragment for fragment in fragments)
	assert all("id=\"comment\"" not in fragment for fragment in fragments)


def test_inline_and_plain_comparisons_are_not_highlights(notebook):
	(notebook / "alpha.md").write_text(
		"Inline `x == y == z` and plain x == y == z.\n",
		encoding="utf-8",
	)
	nb = Notebook()

	rendered = nb.convert_to_html(nb.notes["alpha"])

	assert "<code>x == y == z</code>" in rendered
	assert "plain x == y == z" in rendered
	assert "<mark>" not in rendered


def test_separate_formatting_spans_stay_separate(notebook):
	(notebook / "alpha.md").write_text(
		"~~one~~ and ~~two~~\n\n==three== and ==four==\n",
		encoding="utf-8",
	)
	nb = Notebook()

	rendered = nb.convert_to_html(nb.notes["alpha"])

	assert "<s>one</s> and <s>two</s>" in rendered
	assert "<mark>three</mark> and <mark>four</mark>" in rendered


def test_heading_ids_apply_only_to_headings(notebook):
	(notebook / "alpha.md").write_text(
		"# Real Heading\n\nParagraph with # comment text.\n",
		encoding="utf-8",
	)
	nb = Notebook()

	rendered = nb.convert_to_html(nb.notes["alpha"])

	assert '<h1 id="real-heading">Real Heading</h1>' in rendered
	assert "Paragraph with # comment text." in rendered
	assert 'id="comment-text"' not in rendered


def test_mermaid_rendering_and_pending_state_survive(notebook):
	(notebook / "alpha.md").write_text("Original.\n", encoding="utf-8")
	nb = Notebook()
	note = nb.notes["alpha"]
	note.md_out = "```mermaid\ngraph TD\nA --> B\n```\n"

	rendered = nb.convert_to_html(note)

	assert '<pre class="mermaid">' in rendered
	assert "graph TD" in rendered
	assert note.md_out == "```mermaid\ngraph TD\nA --> B\n```\n"


def test_mermaid_source_is_literal_html_and_readable_without_javascript(notebook):
	nb = Notebook()
	note = nb.notes["other"]
	note.md_out = '```mermaid\ngraph TD\nA["<script>alert(1)</script>"] --> B\n```\n'
	rendered = nb.convert_to_html(note)
	assert '<pre class="mermaid">' in rendered
	assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
	assert "<script>" not in rendered
	assert note.md_out.startswith("```mermaid")


@pytest.mark.parametrize("info", ["python", "{.python #sample}", "", "unknown-language"])
def test_fenced_code_preserves_exact_tabs_unicode_and_trailing_newlines(notebook, info):
	body = '  first\t☃\n\t[[other]] #tag <b>& text\n\n'
	nb = Notebook()
	note = nb.notes["other"]
	note.md_out = f"```{info}\n{body}```\n"
	rendered = nb.convert_to_html(note)
	assert _code_fragments(rendered) == [body]
	assert note.md_out == f"```{info}\n{body}```\n"
	if info == "{.python #sample}":
		assert 'id="sample"' in rendered and 'class="language-python"' in rendered


def test_code_body_placeholders_cannot_collide_with_source_or_each_other(notebook):
	nb = Notebook()
	note = nb.notes["other"]
	first = 'PNBPCODEBODY0TOKEN\nfirst\tblock\n'
	second = 'second\tblock\n'
	note.md_out = f'```text\n{first}```\n\n```text\n{second}```\n'
	assert _code_fragments(nb.convert_to_html(note)) == [first, second]


def test_empty_fences_and_long_code_lines_keep_their_text(notebook):
	nb = Notebook()
	note = nb.notes["other"]
	body = 'x' * 100001 + '\n'
	note.md_out = f'```text\n```\n\n```text\n{body}```\n'
	assert _code_fragments(nb.convert_to_html(note)) == ['', body]


def test_indented_fences_keep_body_indentation_and_unsupported_info_never_leaks_placeholders(notebook):
	nb = Notebook()
	note = nb.notes["other"]
	body = '  print(1)\t☃\n'
	note.md_out = f'  ```python\n{body}  ```\n'
	assert _code_fragments(nb.convert_to_html(note)) == [body]
	note.md_out = f'```python extra-info\n{body}```\n'
	rendered = nb.convert_to_html(note)
	assert 'PNBPCODEBODY' not in rendered
	assert body in html.unescape(rendered)
