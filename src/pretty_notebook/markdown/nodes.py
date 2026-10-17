"""Immutable Markdown values, separate from the legacy string components."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape, unescape
from urllib.parse import quote, unquote, urlsplit


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
    """A constructed node; source locations are introduced by the parser."""

    def to_markdown(self) -> str:
        raise NotImplementedError

    def to_html(self, *, renderer=None, context=None) -> str:
        from .renderers import PythonMarkdownRenderer, RendererContext
        return (renderer or PythonMarkdownRenderer()).render(self, context or RendererContext())


@dataclass(frozen=True)
class Text(Node):
    value: str

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError('Text requires a string.')

    def to_markdown(self):
        # Leading indentation must not turn a paragraph into a code block.
        value = literal(self.value)
        return re.sub(r'^ +', lambda m: '&#32;' * len(m[0]), value)


@dataclass(frozen=True, init=False)
class Container(Node):
    children: tuple[Node, ...]

    def __init__(self, *children):
        values = tuple(Text(child) if isinstance(child, str) else child for child in children)
        if any(not isinstance(child, Node) for child in values):
            raise TypeError('Children must be Markdown nodes or strings.')
        object.__setattr__(self, 'children', values)

    def content(self):
        return ''.join(child.to_markdown() for child in self.children)


@dataclass(frozen=True, init=False)
class BoldText(Container):
    def to_markdown(self):
        return '**' + self.content() + '**'


@dataclass(frozen=True, init=False)
class ItalicText(Container):
    def to_markdown(self):
        return '*' + self.content() + '*'


@dataclass(frozen=True, init=False)
class Paragraph(Container):
    def to_markdown(self):
        return self.content()


@dataclass(frozen=True, init=False)
class Document(Container):
    def to_markdown(self):
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

    def to_markdown(self):
        return '#' * self.level + ' ' + self.content()


@dataclass(frozen=True, init=False)
class ListItem(Document):
    pass


@dataclass(frozen=True, init=False)
class BulletList(Container):
    def __init__(self, *items):
        super().__init__(*(item if isinstance(item, ListItem) else ListItem(Paragraph(item)) for item in items))

    def marker(self, position):
        return '- '

    def to_markdown(self):
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

    def to_markdown(self):
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

    def to_markdown(self):
        return '!' + Link(self.destination, self.alt, title=self.title).to_markdown()


@dataclass(frozen=True)
class CodeBlock(Node):
    body: str
    language: str = ''

    def __post_init__(self):
        if not isinstance(self.body, str) or not isinstance(self.language, str):
            raise TypeError('Code body and language must be strings.')
        if self.language and not re.fullmatch(r'[\w+-]+', self.language):
            raise ValueError('Code language must be a single language identifier.')

    def to_markdown(self):
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

    def to_markdown(self):
        return '[[' + self.target + ']]'
