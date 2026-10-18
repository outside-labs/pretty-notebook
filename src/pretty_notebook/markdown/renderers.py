"""Renderer interfaces and the existing Python-Markdown builder backend."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Protocol
import re

from .nodes import NotebookLink, Node, Text, safe_url


@dataclass(frozen=True)
class RendererContext:
    """Notebook resolution and HTML trust are explicit rendering inputs."""

    notebook: object | None = None
    source_path: str | None = None
    trust: Literal['escape', 'trusted'] = 'escape'
    dialect: Literal['commonmark', 'notebook'] | None = None
    soft_breaks: Literal['newline', 'br'] | None = None

    def __post_init__(self):
        if self.dialect not in {None, 'commonmark', 'notebook'} or self.soft_breaks not in {None, 'newline', 'br'}:
            raise ValueError('Unknown renderer dialect or line-break policy.')
        if self.trust not in {'escape', 'trusted'}:
            raise ValueError('Unknown HTML trust policy.')

    def resolve(self, target: str, *, graph=None, notes_by_path=None) -> str | None:
        from .dialect import slugify
        from urllib.parse import quote
        address = target.split('|', 1)[0].strip()
        if address.startswith('#'):
            return '#' + quote(slugify(address[1:].strip()))
        if self.notebook is None:
            return None
        from pretty_notebook._internal import routes
        graph = graph if graph is not None else self.notebook.graph_index()
        result = graph.resolve(target, source=self.source_path)
        if result.state != 'resolved':
            return None
        notes = notes_by_path if notes_by_path is not None else {note.source_path: note for note in self.notebook.notes.values()}
        note = notes.get(result.path)
        if note is None or (self.dialect == 'notebook' and self.notebook.PUB_LNK_ONLY and not self.notebook.is_publishable(note)):
            return None
        url = routes.public_url(self.notebook.config.get('URL_PREFIX', ''), routes.route_for(note, self.notebook.config).route)
        if '#' in address:
            url += '#' + quote(slugify(address.split('#', 1)[1].strip()))
        return safe_url(url)


class Renderer(Protocol):
    def render(self, document: Node, context: RendererContext) -> str:
        """Render a node using the supplied resolution and trust policy."""
        ...


class PythonMarkdownRenderer:
    """Render constructed values through the production Markdown dependency.

    Builders contain no raw HTML node. Literal text is encoded before Markdown
    processing, independent of the context's HTML policy.
    """

    def render(self, document: Node, context: RendererContext) -> str:
        try:
            import markdown
        except ModuleNotFoundError as error:
            raise RuntimeError('PythonMarkdownRenderer requires pretty-notebook[legacy-markdown].') from error
        if document.source is not None and context.trust != 'trusted':
            raise ValueError('Parsed source requires a typed renderer or an explicit trusted context.')
        from .nodes import Container, Link, RawHtml

        def source(node):
            if isinstance(node, RawHtml) and context.trust != 'trusted':
                return Text(node.value).to_markdown()
            if isinstance(node, NotebookLink):
                address, _, label = node.target.partition('|')
                label = label.strip() or address.strip()
                url = context.resolve(node.target)
                return Link(url, label).to_markdown() if url is not None else Text(label).to_markdown()
            if isinstance(node, Container):
                # Adapt descendants before serializing; original values stay immutable.
                from copy import copy
                adapted = copy(node)
                object.__setattr__(adapted, 'children', tuple(Source(source(child)) for child in node.children))
                return adapted.to_markdown()
            return node.to_markdown()

        return markdown.markdown(source(document), extensions=['fenced_code', 'tables', 'attr_list', 'footnotes', 'toc', 'nl2br'])


@dataclass(frozen=True)
class Source(Node):
    """Internal already-serialized child used only by the backend adapter."""

    value: str

    def _markdown(self):
        return self.value


@dataclass(frozen=True)
class HeadingInfo:
    level: int
    title: str
    identifier: str
    span: object | None = None


@dataclass(frozen=True)
class DiagramInfo:
    language: str
    source: str
    span: object | None = None


@dataclass(frozen=True)
class RenderedMarkdown:
    html: str
    headings: tuple[HeadingInfo, ...] = ()
    languages: tuple[str, ...] = ()
    diagrams: tuple[DiagramInfo, ...] = ()


class TypedRenderer:
    """Render typed nodes directly; escape HTML unless trust is explicit."""

    def render(self, document: Node, context: RendererContext | None = None) -> str:
        return self.render_document(document, context).html

    def render_document(self, document: Node, context: RendererContext | None = None) -> RenderedMarkdown:
        from html import escape
        from urllib.parse import quote
        from .dialect import attributes, slugify
        from .inlines import decode, plain_text
        from .nodes import (
            BlockQuote, BoldText, BulletList, Code, CodeBlock, Container, Document,
            FootnoteDefinition, FootnoteReference, HardBreak, Heading, HighlightedText,
            Image, ImageEmbed, ItalicText, Link, ListItem, Paragraph, RawHtml,
            ReferenceDefinition, SoftBreak, StrikethroughText, Table, TableOfContents,
            TagText, TaskListItem, ThematicBreak,
        )
        context = context or RendererContext()
        notebook_dialect = (context.dialect or getattr(document, 'dialect', 'commonmark')) == 'notebook'
        breaks = context.soft_breaks or ('br' if notebook_dialect else 'newline')

        def text_escape(value):
            return escape(value, quote=False).replace(chr(34), '&quot;')

        def url(value):
            try:
                safe_url(value)
            except ValueError:
                return ''
            return text_escape(quote(value, safe="/:?#@!$&'()*+,;=%-._~"))

        def attrs(values, **overrides):
            values = {**dict(values), **overrides}
            allowed = {'id', 'class', 'title', 'lang', 'dir', 'role'}
            return ''.join(' ' + key + '="' + text_escape(str(value)) + '"' for key, value in sorted(values.items())
                           if value is not None and (key in allowed or re.fullmatch(r'(?:data|aria)-[a-z0-9-]+', key)))

        def walk(node, *, definitions=True):
            yield node
            if isinstance(node, FootnoteDefinition) and not definitions:
                return
            for child in getattr(node, 'children', ()):
                yield from walk(child, definitions=definitions)

        all_nodes = tuple(walk(document))
        headings, heading_ids, used_ids = [], {}, set()
        languages, diagrams, code_options = [], [], {}
        footnotes, references, counts = {}, {}, {}
        for node in all_nodes:
            if isinstance(node, Heading):
                label = re.sub(r'\s+', ' ', plain_text(node.children)).strip()
                identifier = dict(node.attributes).get('id', slugify(label))
                while identifier in used_ids or not identifier:
                    match = re.match(r'^(.*)_([0-9]+)$', identifier)
                    identifier = f'{match[1]}_{int(match[2]) + 1}' if match else identifier + '_1'
                used_ids.add(identifier)
                heading_ids[id(node)] = identifier
                headings.append(HeadingInfo(node.level, label, identifier, node.span))
            elif isinstance(node, CodeBlock):
                info = decode(node.info).strip() if node.info else node.language
                options = attributes(info) if notebook_dialect and info.startswith('{') else None
                options = {**dict(options or ()), **dict(node.attributes)}
                classes = options.pop('class', '').split()
                language = classes.pop(0) if classes else info.split()[0] if info and not info.startswith('{') else node.language
                if classes:
                    options['class'] = ' '.join(classes)
                code_options[id(node)] = language, tuple(options.items())
                if language and language not in languages:
                    languages.append(language)
                if notebook_dialect and language.casefold() == 'mermaid':
                    diagrams.append(DiagramInfo('mermaid', node.body, node.span))
            elif isinstance(node, FootnoteDefinition):
                footnotes.setdefault(node.label, node)
        reference_nodes = [node for node in walk(document, definitions=False) if isinstance(node, FootnoteReference)]
        reference_nodes += [node for definition in footnotes.values() for node in walk(definition) if isinstance(node, FootnoteReference)]
        for node in reference_nodes:
            counts[node.label] = counts.get(node.label, 0) + 1
            references[id(node)] = counts[node.label]
        footnote_numbers = {label: position + 1 for position, label in enumerate(footnotes)}
        graph, note_paths, resolutions = None, None, {}

        def resolve(target):
            nonlocal graph, note_paths
            if target not in resolutions:
                if context.notebook is not None and graph is None:
                    graph = context.notebook.graph_index()
                    note_paths = {note.source_path: note for note in context.notebook.notes.values()}
                resolutions[target] = context.resolve(target, graph=graph, notes_by_path=note_paths)
            return resolutions[target]

        def inline(node):
            if isinstance(node, TagText) and context.notebook is not None:
                if context.notebook.config.get('HIDE_COMMIT_TAG') and node.value == context.notebook.COMMIT_TAG:
                    return ''
            if isinstance(node, Text):
                return text_escape(node.value)
            if isinstance(node, Code):
                return '<code' + attrs(node.attributes) + '>' + text_escape(node.value) + '</code>'
            if isinstance(node, HardBreak):
                return '<br />\n'
            if isinstance(node, SoftBreak):
                return '<br />\n' if breaks == 'br' else '\n'
            if isinstance(node, RawHtml):
                return node.value if context.trust == 'trusted' else text_escape(node.value)
            if isinstance(node, NotebookLink):
                address, _, label = node.target.partition('|')
                label = text_escape(label.strip() or address.strip().replace('#', ' > '))
                resolved = resolve(node.target)
                # Preserve the established notebook-link attribute spelling.
                if resolved is None:
                    return label
                if notebook_dialect:
                    return "<a href='" + url(resolved).replace("'", '&#39;') + "'>" + label + '</a>'
                return '<a href="' + url(resolved) + '">' + label + '</a>'
            if isinstance(node, ImageEmbed):
                from pretty_notebook._internal.routes import public_image_url
                image_url = public_image_url(context.notebook.config if context.notebook else {}, node.name)
                return '<img class="img-fluid" src=\'' + url(image_url).replace("'", '&#39;') + "'>"
            if isinstance(node, Image):
                values = dict(node.attributes)
                if node.title is not None:
                    values.setdefault('title', node.title)
                return '<img src="' + url(node.destination) + '" alt="' + text_escape(node.alt) + '"' + attrs(values) + ' />'
            if isinstance(node, FootnoteReference):
                label = node.label
                if label not in footnotes:
                    return text_escape('[^' + label + ']')
                occurrence = references.get(id(node), 1)
                ref = 'fnref' + (str(occurrence) if occurrence > 1 else '') + ':' + label
                return '<sup id="' + text_escape(ref) + '"><a class="footnote-ref" href="' + url('#fn:' + label) + '">' + str(footnote_numbers[label]) + '</a></sup>'
            content = ''.join(inline(child) for child in node.children) if isinstance(node, Container) else ''
            if isinstance(node, Link):
                extra = ' rel="nofollow" target="_blank"' if notebook_dialect else ''
                values = dict(node.attributes)
                if node.title is not None:
                    values.setdefault('title', node.title)
                rendered = '<a' + extra + ' href="' + url(node.destination) + '"' + attrs(values) + '>' + content + '</a>'
                if notebook_dialect:
                    from pretty_notebook._internal.icons import render_icon
                    rendered += ' ' + render_icon('external', size='sm')
                return rendered
            tag = 'strong' if isinstance(node, BoldText) else 'em' if isinstance(node, ItalicText) else 's' if isinstance(node, StrikethroughText) else 'mark' if isinstance(node, HighlightedText) else None
            if tag:
                return '<' + tag + attrs(node.attributes) + '>' + content + '</' + tag + '>'
            raise TypeError(f'Unsupported inline node: {type(node).__name__}')

        def toc():
            roots, stack = [], []
            for heading in headings:
                entry = [heading, []]
                while stack and stack[-1][0].level >= heading.level:
                    stack.pop()
                (stack[-1][1] if stack else roots).append(entry)
                stack.append(entry)
            def items(entries):
                if not entries:
                    return ''
                return '<ul>\n' + ''.join('<li><a href="' + url('#' + item.identifier) + '">' + text_escape(item.title) + '</a>' + ('\n' + items(children) if children else '') + '</li>\n' for item, children in entries) + '</ul>\n'
            return '<div class="toc">\n' + items(roots) + '</div>\n'

        def block(node, tight=False):
            if isinstance(node, Heading):
                tag = f'h{node.level}'
                values = dict(node.attributes)
                if notebook_dialect:
                    values['id'] = heading_ids[id(node)]
                return '<' + tag + attrs(values) + '>' + ''.join(inline(child) for child in node.children) + '</' + tag + '>\n'
            if isinstance(node, Paragraph):
                content = ''.join(inline(child) for child in node.children)
                return content + '\n' if tight else '<p' + attrs(node.attributes) + '>' + content + '</p>\n'
            if isinstance(node, CodeBlock):
                language, options = code_options[id(node)]
                if notebook_dialect and language.casefold() == 'mermaid':
                    return '<pre class="mermaid">' + text_escape(node.body) + '</pre>\n'
                code_attr = ' class="language-' + text_escape(language) + '"' if language else ''
                body = node.body
                if node.source is None and body and not body.endswith('\n'):
                    body += '\n'
                return '<pre' + attrs(options) + '><code' + code_attr + '>' + text_escape(body) + '</code></pre>\n'
            if isinstance(node, ThematicBreak):
                return '<hr />\n'
            if isinstance(node, BlockQuote):
                return '<blockquote>\n' + ''.join(block(child) for child in node.children) + '</blockquote>\n'
            if isinstance(node, Table):
                def row(item, header=False):
                    tag = 'th' if header else 'td'
                    cells = []
                    for position, cell in enumerate(item.children):
                        alignment = node.alignments[position]
                        style = ' style="text-align: ' + alignment + ';"' if alignment else ''
                        cells.append('<' + tag + style + attrs(cell.attributes) + '>' + ''.join(inline(child) for child in cell.children) + '</' + tag + '>\n')
                    return '<tr>\n' + ''.join(cells) + '</tr>\n'
                return '<table' + attrs(node.attributes) + '>\n<thead>\n' + row(node.children[0], True) + '</thead>\n<tbody>\n' + ''.join(row(item) for item in node.children[1:]) + '</tbody>\n</table>\n'
            if isinstance(node, TableOfContents):
                return toc()
            if isinstance(node, BulletList):
                ordered = hasattr(node, 'start')
                tag = 'ol' if ordered else 'ul'
                attr = f' start="{node.start}"' if ordered and node.start != 1 else ''
                if any(isinstance(child, TaskListItem) for child in node.children):
                    attr += ' class="task-list"'
                return '<' + tag + attr + '>\n' + ''.join(block(child, node.tight) for child in node.children) + '</' + tag + '>\n'
            if isinstance(node, ListItem):
                visible = [child for child in node.children if not isinstance(child, (ReferenceDefinition, FootnoteDefinition))]
                if not visible:
                    return '<li></li>\n'
                content = ''.join(block(child, tight) for child in visible)
                attr = ''
                if isinstance(node, TaskListItem):
                    checkbox = '<input type="checkbox" disabled=""' + (' checked=""' if node.checked else '') + ' /> '
                    content = checkbox + content if tight else content.replace('>', '>' + checkbox, 1)
                    attr = ' class="task-list-item"'
                before = '' if tight and isinstance(visible[0], Paragraph) else '\n'
                if tight and isinstance(visible[-1], Paragraph):
                    content = content.removesuffix('\n')
                return '<li' + attr + '>' + before + content + '</li>\n'
            if isinstance(node, FootnoteDefinition):
                return ''
            if isinstance(node, Document):
                return ''.join(block(child) for child in node.children)
            if isinstance(node, ReferenceDefinition):
                return ''
            if isinstance(node, RawHtml):
                return inline(node)
            return '<p>' + inline(node) + '</p>\n'

        rendered = block(document)
        if footnotes:
            entries = []
            for label, definition in footnotes.items():
                content = ''.join(block(child) for child in definition.children)
                backrefs = ''.join('<a class="footnote-backref" href="' + url('#fnref' + (str(number) if number > 1 else '') + ':' + label) + '" title="Jump back to footnote ' + str(footnote_numbers[label]) + ' in the text">&#8617;</a>' for number in range(1, counts.get(label, 0) + 1))
                if backrefs:
                    if content.endswith('</p>\n'):
                        content = content[:-5] + '&#160;' + backrefs + '</p>\n'
                    else:
                        content += '<p>' + backrefs + '</p>\n'
                entries.append('<li id="' + text_escape('fn:' + label) + '">\n' + content + '</li>\n')
            rendered += '<div class="footnote">\n<hr />\n<ol>\n' + ''.join(entries) + '</ol>\n</div>\n'
        return RenderedMarkdown(rendered.removesuffix('\n'), tuple(headings), tuple(languages), tuple(diagrams))


class NotebookRenderer(TypedRenderer):
    def render_document(self, document, context=None):
        context = replace(context or RendererContext(), dialect='notebook')
        return super().render_document(document, context)


def render_notebook(source, *, context=None, options=None):
    from .dialect import parse_notebook
    return NotebookRenderer().render_document(parse_notebook(source, options=options), context)
