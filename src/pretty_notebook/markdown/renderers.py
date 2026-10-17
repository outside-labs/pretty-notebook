"""Renderer interfaces and the existing Python-Markdown builder backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .nodes import NotebookLink, Node, Text, safe_url


@dataclass(frozen=True)
class RendererContext:
    """Notebook resolution and HTML trust are explicit rendering inputs."""

    notebook: object | None = None
    source_path: str | None = None
    trust: Literal['escape', 'trusted'] = 'escape'

    def __post_init__(self):
        if self.trust not in {'escape', 'trusted'}:
            raise ValueError('Unknown HTML trust policy.')

    def resolve(self, target: str) -> str | None:
        if self.notebook is None:
            return None
        from pretty_notebook._internal import routes
        from urllib.parse import quote
        graph = self.notebook.graph_index()
        result = graph.resolve(target, source=self.source_path)
        if result.state != 'resolved':
            return None
        note = next((note for note in self.notebook.notes.values() if note.source_path == result.path), None)
        if note is None:
            return None
        url = routes.public_url(self.notebook.config.get('URL_PREFIX', ''), routes.route_for(note, self.notebook.config).route)
        address = target.split('|', 1)[0]
        if '#' in address:
            from markdown.extensions.toc import slugify
            url += '#' + quote(slugify(address.split('#', 1)[1].strip(), '-'))
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
        import markdown
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


class TypedRenderer:
    """Render typed nodes directly; escape HTML unless trust is explicit."""

    def render(self, document: Node, context: RendererContext | None = None) -> str:
        from html import escape
        from urllib.parse import quote
        from .inlines import decode
        from .nodes import (
            BlockQuote, BoldText, BulletList, Code, CodeBlock, Container,
            Document, HardBreak, Heading, Image, ItalicText, Link, ListItem,
            Paragraph, RawHtml, ReferenceDefinition, SoftBreak, ThematicBreak,
        )
        context = context or RendererContext()

        def text_escape(value):
            return escape(value, quote=False).replace(chr(34), '&quot;')

        def url(value):
            try:
                safe_url(value)
            except ValueError:
                return ''
            return text_escape(quote(value, safe="/:?#@!$&'()*+,;=%-._~"))

        def title(value):
            return '' if value is None else ' title="' + text_escape(value) + '"'

        def inline(node):
            if isinstance(node, Text):
                return text_escape(node.value)
            if isinstance(node, Code):
                return '<code>' + text_escape(node.value) + '</code>'
            if isinstance(node, HardBreak):
                return '<br />\n'
            if isinstance(node, SoftBreak):
                return '\n'
            if isinstance(node, RawHtml):
                return node.value if context.trust == 'trusted' else text_escape(node.value)
            if isinstance(node, NotebookLink):
                address, _, label = node.target.partition('|')
                label = text_escape(label.strip() or address.strip())
                resolved = context.resolve(node.target)
                return '<a href="' + url(resolved) + '">' + label + '</a>' if resolved is not None else label
            if isinstance(node, Image):
                return '<img src="' + url(node.destination) + '" alt="' + text_escape(node.alt) + '"' + title(node.title) + ' />'
            content = ''.join(inline(child) for child in node.children) if isinstance(node, Container) else ''
            if isinstance(node, Link):
                return '<a href="' + url(node.destination) + '"' + title(node.title) + '>' + content + '</a>'
            if isinstance(node, BoldText):
                return '<strong>' + content + '</strong>'
            if isinstance(node, ItalicText):
                return '<em>' + content + '</em>'
            raise TypeError(f'Unsupported inline node: {type(node).__name__}')

        def block(node, tight=False):
            if isinstance(node, Heading):
                tag = f'h{node.level}'
                return '<' + tag + '>' + ''.join(inline(child) for child in node.children) + '</' + tag + '>\n'
            if isinstance(node, Paragraph):
                content = ''.join(inline(child) for child in node.children)
                return content + '\n' if tight else '<p>' + content + '</p>\n'
            if isinstance(node, CodeBlock):
                language = decode(node.info).split()[0] if node.info else node.language
                attr = ' class="language-' + text_escape(language) + '"' if language else ''
                return '<pre><code' + attr + '>' + text_escape(node.body) + '</code></pre>\n'
            if isinstance(node, ThematicBreak):
                return '<hr />\n'
            if isinstance(node, BlockQuote):
                return '<blockquote>\n' + ''.join(block(child) for child in node.children) + '</blockquote>\n'
            if isinstance(node, BulletList):
                ordered = hasattr(node, 'start')
                tag = 'ol' if ordered else 'ul'
                attr = f' start="{node.start}"' if ordered and node.start != 1 else ''
                return '<' + tag + attr + '>\n' + ''.join(block(child, node.tight) for child in node.children) + '</' + tag + '>\n'
            if isinstance(node, ListItem):
                visible = [child for child in node.children if not isinstance(child, ReferenceDefinition)]
                if not visible:
                    return '<li></li>\n'
                content = ''.join(block(child, tight) for child in visible)
                before = '' if tight and isinstance(visible[0], Paragraph) else '\n'
                if tight and isinstance(visible[-1], Paragraph):
                    content = content.removesuffix('\n')
                return '<li>' + before + content + '</li>\n'
            if isinstance(node, Document):
                return ''.join(block(child) for child in node.children)
            if isinstance(node, ReferenceDefinition):
                return ''
            if isinstance(node, RawHtml):
                return inline(node)
            return '<p>' + inline(node) + '</p>\n'

        return block(document).removesuffix('\n')
