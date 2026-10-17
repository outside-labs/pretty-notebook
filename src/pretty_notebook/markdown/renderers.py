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
        from .nodes import Container, Link

        def source(node):
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

    def to_markdown(self):
        return self.value
