"""Immutable Markdown values, separate from the legacy string components."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape, unescape
from urllib.parse import quote, unquote, urlsplit
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parser import Diagnostic, SourceSpan


def literal(value: str) -> str:
    """Encode punctuation so literal text cannot introduce Markdown or HTML."""
    return ''.join(f'&#{ord(c)};' if c in r'\`*_{}[]()#+-.!|>~=<&' or c in '\r\n' else c for c in value)


def safe_url(value: str) -> str:
    """Allow ordinary web/mail/relative destinations, never executable schemes."""
    if not isinstance(value, str):
        raise TypeError('URL must be a string.')
    decoded = unquote(unescape(value)).strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in decoded) or '\\' in decoded:
        raise ValueError('URL contains control characters or backslashes.')
    if urlsplit(decoded).scheme.casefold() not in {'', 'http', 'https', 'mailto'} or decoded.startswith('//'):
        raise ValueError('URL scheme is not allowed.')
    return value


@dataclass(frozen=True, kw_only=True)
class Node:
    """An immutable value with optional exact original source and location."""

    span: SourceSpan | None = field(default=None, compare=False, repr=False)
    source: str | None = field(default=None, compare=False, repr=False)
    positions: tuple[int, ...] | None = field(default=None, compare=False, repr=False)
    attributes: tuple[tuple[str, str], ...] = field(default=(), kw_only=True)

    def to_markdown(self) -> str:
        return self.source if self.source is not None else self._markdown()

    def _markdown(self) -> str:
        raise NotImplementedError

    def to_html(self, *, renderer=None, context=None) -> str:
        from .renderers import RendererContext, TypedRenderer
        default = TypedRenderer()
        return (renderer or default).render(self, context or RendererContext())


@dataclass(frozen=True)
class Text(Node):
    value: str

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError('Text requires a string.')

    def _markdown(self):
        # Leading indentation must not turn a paragraph into a code block.
        value = literal(self.value)
        return re.sub(r'^ +', lambda m: '&#32;' * len(m[0]), value)


@dataclass(frozen=True, init=False)
class Container(Node):
    children: tuple[Node, ...]

    def __init__(self, *children, span=None, source=None, positions=None, attributes=()):
        values = tuple(Text(child) if isinstance(child, str) else child for child in children)
        if any(not isinstance(child, Node) for child in values):
            raise TypeError('Children must be Markdown nodes or strings.')
        object.__setattr__(self, 'children', values)
        object.__setattr__(self, 'span', span)
        object.__setattr__(self, 'source', source)
        object.__setattr__(self, 'positions', positions)
        object.__setattr__(self, 'attributes', tuple(attributes))

    def content(self):
        return ''.join(child.to_markdown() for child in self.children)


@dataclass(frozen=True, init=False)
class BoldText(Container):
    def _markdown(self):
        return '**' + self.content() + '**'


@dataclass(frozen=True, init=False)
class ItalicText(Container):
    def _markdown(self):
        return '*' + self.content() + '*'


@dataclass(frozen=True, init=False)
class Paragraph(Container):
    def _markdown(self):
        return self.content()


@dataclass(frozen=True, init=False)
class Document(Container):
    diagnostics: tuple[Diagnostic, ...] = ()
    dialect: str = 'commonmark'

    def _markdown(self):
        return '\n\n'.join(child.to_markdown() for child in self.children)


MarkdownText = Document


@dataclass(frozen=True, init=False)
class Heading(Container):
    level: int

    def __init__(self, level, *children):
        if type(level) is not int or not 1 <= level <= 6:
            raise ValueError('Heading level must be an integer from 1 to 6.')
        super().__init__(*children)
        object.__setattr__(self, 'level', level)

    def _markdown(self):
        return '#' * self.level + ' ' + self.content()


@dataclass(frozen=True, init=False)
class ListItem(Document):
    pass


@dataclass(frozen=True, init=False)
class BulletList(Container):
    tight: bool = True

    def __init__(self, *items):
        super().__init__(*(item if isinstance(item, ListItem) else ListItem(Paragraph(item)) for item in items))

    def marker(self, position):
        return '- '

    def _markdown(self):
        lines = []
        for position, item in enumerate(self.children):
            marker = self.marker(position)
            text = item.to_markdown().split('\n')
            lines.append(marker + text[0])
            lines.extend('    ' + line if line else '' for line in text[1:])
        return '\n'.join(lines)


@dataclass(frozen=True, init=False)
class OrderedList(BulletList):
    start: int

    def __init__(self, *items, start=1):
        if type(start) is not int or not 0 <= start <= 999999999:
            raise ValueError('List start must be an integer from 0 to 999999999.')
        super().__init__(*items)
        object.__setattr__(self, 'start', start)

    def marker(self, position):
        return f'{self.start + position}. '


@dataclass(frozen=True, init=False)
class Link(Container):
    destination: str
    title: str | None

    def __init__(self, destination, *children, title=None):
        super().__init__(*(children or (destination,)))
        object.__setattr__(self, 'destination', safe_url(destination))
        if title is not None and not isinstance(title, str):
            raise TypeError('Link title must be a string.')
        object.__setattr__(self, 'title', title)

    def _markdown(self):
        destination = quote(self.destination, safe='/:#?&=%@+,$;~')
        title = '' if self.title is None else ' "' + escape(self.title, quote=True) + '"'
        return f'[{self.content()}](<{destination}>{title})'


@dataclass(frozen=True)
class Image(Node):
    destination: str
    alt: str = ''
    title: str | None = None

    def __post_init__(self):
        safe_url(self.destination)
        if not isinstance(self.alt, str) or (self.title is not None and not isinstance(self.title, str)):
            raise TypeError('Image alt and title must be strings.')

    def _markdown(self):
        return '!' + Link(self.destination, self.alt, title=self.title).to_markdown()


@dataclass(frozen=True)
class CodeBlock(Node):
    body: str
    language: str = ''
    info: str = field(default='', kw_only=True)

    def __post_init__(self):
        if not isinstance(self.body, str) or not isinstance(self.language, str):
            raise TypeError('Code body and language must be strings.')
        if self.language and not re.fullmatch(r'[\w+-]+', self.language):
            raise ValueError('Code language must be a single language identifier.')

    def _markdown(self):
        longest = max((len(match[0]) for match in re.finditer(r'`+', self.body)), default=0)
        fence = '`' * max(3, longest + 1)
        return fence + self.language + '\n' + self.body + ('' if self.body.endswith('\n') or not self.body else '\n') + fence


def from_component(value) -> Node:
    """Adapt legacy values without changing their constructors or string semantics."""
    from pretty_notebook.models.components import CodeBlock as LegacyCode, Link as WikiLink, Tag, Url
    if isinstance(value, LegacyCode):
        return CodeBlock(value.body, value.lang or '')
    if isinstance(value, WikiLink):
        return NotebookLink(str(value))
    if isinstance(value, Url):
        return Link(str(value))
    if isinstance(value, Tag):
        return Text(str(value))
    raise TypeError('Expected a legacy Link, Tag, Url, or CodeBlock.')


@dataclass(frozen=True)
class NotebookLink(Node):
    target: str

    def _markdown(self):
        return '[[' + self.target + ']]'


@dataclass(frozen=True, init=False)
class BlockQuote(Document):
    def _markdown(self):
        return '\n'.join('> ' + line for line in super()._markdown().split('\n'))


@dataclass(frozen=True)
class ThematicBreak(Node):
    def _markdown(self):
        return '---'


@dataclass(frozen=True)
class RawHtml(Node):
    value: str

    def _markdown(self):
        return self.value


@dataclass(frozen=True)
class ReferenceDefinition(Node):
    label: str
    destination: str
    title: str | None = None

    def _markdown(self):
        return '[' + self.label + ']: ' + self.destination


@dataclass(frozen=True)
class Code(Node):
    value: str

    def _markdown(self):
        longest = max((len(m[0]) for m in re.finditer(r'`+', self.value)), default=0)
        fence = '`' * (longest + 1)
        pad = ' ' if self.value.startswith(('`', ' ')) or self.value.endswith(('`', ' ')) else ''
        return fence + pad + self.value + pad + fence


@dataclass(frozen=True)
class SoftBreak(Node):
    def _markdown(self):
        return '\n'


@dataclass(frozen=True)
class HardBreak(Node):
    def _markdown(self):
        return '  \n'


@dataclass(frozen=True, init=False)
class StrikethroughText(Container):
    def _markdown(self):
        return '~~' + self.content() + '~~'


@dataclass(frozen=True, init=False)
class HighlightedText(Container):
    def _markdown(self):
        return '==' + self.content() + '=='


@dataclass(frozen=True, init=False)
class TableCell(Container):
    def _markdown(self):
        return self.content()


@dataclass(frozen=True, init=False)
class TableRow(Container):
    def _markdown(self):
        return '| ' + ' | '.join(child.to_markdown() for child in self.children) + ' |'


@dataclass(frozen=True, init=False)
class Table(Container):
    alignments: tuple[str | None, ...]

    def __init__(self, header, *rows, alignments=()):
        if not all(isinstance(row, TableRow) for row in (header, *rows)):
            raise TypeError('Tables contain TableRow values.')
        super().__init__(header, *rows)
        values = tuple(alignments) or (None,) * len(header.children)
        if len(values) != len(header.children) or any(value not in {None, 'left', 'center', 'right'} for value in values):
            raise ValueError('Table alignments must match the header width.')
        object.__setattr__(self, 'alignments', values)

    def _markdown(self):
        markers = {None: '---', 'left': ':---', 'center': ':---:', 'right': '---:'}
        lines = [self.children[0].to_markdown(), '| ' + ' | '.join(markers[value] for value in self.alignments) + ' |']
        return '\n'.join(lines + [row.to_markdown() for row in self.children[1:]])


@dataclass(frozen=True, init=False)
class TaskListItem(ListItem):
    checked: bool

    def __init__(self, *children, checked=False):
        if type(checked) is not bool:
            raise TypeError('Task checked must be a boolean.')
        super().__init__(*children)
        object.__setattr__(self, 'checked', checked)

    def _markdown(self):
        return ('[x] ' if self.checked else '[ ] ') + super()._markdown()


@dataclass(frozen=True, init=False)
class FootnoteDefinition(Document):
    label: str

    def __init__(self, label, *children):
        super().__init__(*children)
        object.__setattr__(self, 'label', label)

    def _markdown(self):
        return '[^' + self.label + ']: ' + super()._markdown().replace('\n', '\n    ')


@dataclass(frozen=True)
class FootnoteReference(Node):
    label: str

    def _markdown(self):
        return '[^' + self.label + ']'


@dataclass(frozen=True)
class ImageEmbed(Node):
    name: str

    def _markdown(self):
        return '![[' + self.name + ']]'


@dataclass(frozen=True)
class TagText(Text):
    pass


@dataclass(frozen=True)
class TableOfContents(Node):
    def _markdown(self):
        return '[TOC]'


@dataclass(frozen=True, init=False)
class Mermaid(CodeBlock):
    def __init__(self, body):
        super().__init__(body, 'mermaid')
