"""Bounded, source-preserving block parsing for the notebook Markdown dialect."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field, replace

from .nodes import (
    BlockQuote, BulletList, CodeBlock, Document, Heading, ListItem, OrderedList,
    Paragraph, RawHtml, ReferenceDefinition, Text, ThematicBreak,
)


@dataclass(frozen=True)
class SourceSpan:
    """Half-open code-point offsets and one-based line/column coordinates."""

    start: int
    end: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    span: SourceSpan
    severity: str = 'info'


class ParseLimitError(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


@dataclass(frozen=True)
class ParseOptions:
    max_characters: int = 2_000_000
    max_nesting: int = 64
    max_nodes: int = 100_000

    def __post_init__(self):
        for value in (self.max_characters, self.max_nesting, self.max_nodes):
            if type(value) is not int or value < 1:
                raise ValueError('Parser limits must be positive integers.')
        if self.max_nesting > 64:
            raise ValueError('Maximum supported nesting limit is 64.')


class SourceMap:
    def __init__(self, source):
        self.source = source
        self.starts = [0, *(match.end() for match in re.finditer(r'\r\n|\r|\n', source))]

    def span(self, start, end):
        left, right = bisect.bisect_right(self.starts, start) - 1, bisect.bisect_right(self.starts, end) - 1
        return SourceSpan(start, end, left + 1, start - self.starts[left] + 1,
                          right + 1, end - self.starts[right] + 1)


@dataclass(frozen=True)
class _Line:
    text: str
    positions: tuple[int, ...]
    start: int
    end: int
    newline: int | None
    lazy: bool = False
    tabs: dict[int, int] = field(default_factory=dict)

    def cut(self, count):
        return _Line(self.text[count:], self.positions[count:],
                     self.positions[count] if count < len(self.positions) else (self.newline if self.newline is not None else self.end),
                     self.end, self.newline, self.lazy, self.tabs)

    @property
    def blank(self):
        return not self.text.strip(' \t')

    @property
    def indent(self):
        return len(self.text) - len(self.text.lstrip(' '))


def _lines(source):
    offset = 0
    for raw in re.findall(r'[^\r\n]*(?:\r\n|\r|\n|$)', source):
        if not raw:
            continue
        text = raw.rstrip('\r\n')
        positions, expanded, column, tabs = [], [], 0, {}
        for index, char in enumerate(text):
            width = 4 - column % 4 if char == '\t' else 1
            if char == '\t':
                tabs[offset + index] = width
            expanded.append(' ' * width if char == '\t' else char.replace('\x00', '\ufffd'))
            positions.extend([offset + index] * width)
            column += width
        yield _Line(''.join(expanded), tuple(positions), offset, offset + len(raw),
                    offset + len(text) if len(raw) > len(text) else None, tabs=tabs)
        offset += len(raw)


_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_ATX = re.compile(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$')
_SETEXT = re.compile(r'^ {0,3}(=+|-+)[ \t]*$')
_QUOTE = re.compile(r'^ {0,3}>[ \t]?')
_LIST = re.compile(r'^( {0,3})([-+*]|[0-9]{1,9}[.)])([ \t]+|$)(.*)$')


def _thematic(text):
    return bool(re.fullmatch(r' {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})', text))


def _fence(text):
    match = _FENCE.match(text)
    return match if match and not (match[1].startswith('`') and '`' in match[2]) else None


def _list(text):
    match = _LIST.match(text)
    if not match:
        return None
    indent, marker, whitespace, content = match.groups()
    width = len(whitespace)
    if not content.strip():
        width = 1
    if width > 4:
        content = ' ' * (width - 1) + content
        width = 1
    return len(indent), marker, len(indent) + len(marker) + max(1, width), content


def _interrupt(line, *, paragraph=True):
    marker = _list(line.text)
    list_break = marker and (not paragraph or (marker[3] and (not marker[1][0].isdigit() or int(marker[1][:-1]) == 1)))
    return bool(_ATX.match(line.text) or _fence(line.text) or _thematic(line.text) or _QUOTE.match(line.text) or list_break)


class _Parser:
    def __init__(self, source, options):
        self.mapping, self.options = SourceMap(source), options
        self.diagnostics, self.count = [], 0

    def fail(self, code, message, start=0, end=0):
        raise ParseLimitError(Diagnostic(code, message, self.mapping.span(start, end), 'error'))

    def locate(self, node, start, end, positions=None):
        self.count += 1
        if self.count > self.options.max_nodes:
            self.fail('node-limit', 'Markdown node limit exceeded.', start, end)
        object.__setattr__(node, 'span', self.mapping.span(start, end))
        object.__setattr__(node, 'source', self.mapping.source[start:end])
        object.__setattr__(node, 'positions', positions)
        return node

    def semantic(self, line, start=0):
        # Recover full original tabs; a partially consumed indentation tab
        # contributes only its remaining virtual spaces.
        text, positions, index = [], [], start
        while index < len(line.text):
            offset = line.positions[index]
            end = index + 1
            while end < len(line.text) and line.positions[end] == offset:
                end += 1
            char = self.mapping.source[offset]
            if char == '\t':
                width = line.tabs.get(offset, 1)
                value = '\t' if end - index == width else ' ' * (end - index)
            else:
                value = line.text[index:end]
            text.append(value)
            positions.extend([offset] * len(value))
            index = end
        return ''.join(text), tuple(positions)

    def inline_text(self, lines, *, trim=False):
        values, positions = [], []
        for index, line in enumerate(lines):
            cut = len(line.text) - len(line.text.lstrip(' \t'))
            text, mapped = self.semantic(line, cut)
            if trim:
                text = text.rstrip(' \t')
            values.append(text)
            positions.extend(mapped[:len(text)])
            if index < len(lines) - 1:
                values.append('\n')
                positions.append(line.newline if line.newline is not None else line.end)
        value = ''.join(values)
        start = positions[0] if positions else lines[0].start
        end = positions[-1] + 1 if positions else start
        return self.locate(Text(value), start, end, tuple(positions))

    def blocks(self, lines, depth=0):
        if depth > self.options.max_nesting:
            self.fail('nesting-limit', 'Markdown nesting limit exceeded.', lines[0].start, lines[-1].end)
        nodes, index = [], 0
        while index < len(lines):
            line = lines[index]
            if line.blank:
                index += 1
                continue
            begin = index
            fence, heading = _fence(line.text), _ATX.match(line.text)
            if fence:
                marker, info = fence[1], fence[2].strip()
                indent, body = line.indent, []
                index += 1
                closed = False
                while index < len(lines):
                    current = lines[index]
                    if re.fullmatch(r' {0,3}' + re.escape(marker[0]) + '{' + str(len(marker)) + r',}[ \t]*', current.text):
                        closed = True
                        index += 1
                        break
                    body.append(self.semantic(current, min(indent, current.indent))[0] + '\n')
                    index += 1
                language = info.split()[0] if info else ''
                node = CodeBlock(''.join(body), language if re.fullmatch(r'[\w+-]*', language) else '', info=info)
                if not closed:
                    self.diagnostics.append(Diagnostic('unclosed-fence', 'Code fence continues through end of container.', self.mapping.span(line.start, lines[index - 1].end)))
            elif heading:
                content = heading[2] or ''
                content = re.sub(r'[ \t]+#+[ \t]*$', '', content).strip(' \t')
                content_start = line.text.find(content, len(heading[1])) if content else len(line.text)
                content_line = line.cut(content_start)
                content_line = _Line(content, content_line.positions[:len(content)], content_line.start, content_line.end, None, tabs=content_line.tabs)
                node = Heading(len(heading[1]), self.inline_text([content_line]))
                index += 1
            elif _thematic(line.text):
                node = ThematicBreak()
                index += 1
            elif line.indent >= 4:
                body = []
                while index < len(lines) and (lines[index].blank or lines[index].indent >= 4):
                    body.append(self.semantic(lines[index], min(4, len(lines[index].text)))[0])
                    index += 1
                while body and not body[-1].strip():
                    body.pop()
                    index -= 1
                node = CodeBlock('\n'.join(body) + '\n')
            elif line.text.lstrip().startswith('<!--'):
                body = []
                while index < len(lines):
                    body.append(self.semantic(lines[index])[0])
                    index += 1
                    if '-->' in body[-1]:
                        break
                node = RawHtml('\n'.join(body) + '\n')
            elif re.match(r'^ {0,3}\[[^]\n]+\]:[ \t]*\S', line.text):
                definition = re.match(r'^ {0,3}\[([^]\n]+)\]:[ \t]*(.*)$', line.text)
                node = ReferenceDefinition(definition[1], definition[2])
                index += 1
            elif _QUOTE.match(line.text):
                inner, lazy = [], False
                while index < len(lines):
                    current = lines[index]
                    quote = _QUOTE.match(current.text)
                    if quote:
                        stripped = current.cut(quote.end())
                        inner.append(stripped)
                        probe = stripped
                        while _QUOTE.match(probe.text) or _list(probe.text):
                            quote_prefix = _QUOTE.match(probe.text)
                            probe = probe.cut(quote_prefix.end() if quote_prefix else _list(probe.text)[2])
                        lazy = not probe.blank and probe.indent < 4 and not _interrupt(probe) and not _SETEXT.match(probe.text)
                    elif lazy and not current.blank and not _interrupt(current):
                        inner.append(replace(current, lazy=True))
                    else:
                        break
                    index += 1
                node = BlockQuote(*self.blocks(inner, depth + 1))
            elif _list(line.text):
                first = _list(line.text)
                base_indent, first_marker = first[:2]
                ordered = first_marker[0].isdigit()
                style = first_marker[-1] if ordered else first_marker
                items, loose, previous_width = [], False, first[2]
                while index < len(lines):
                    marker = _list(lines[index].text)
                    if not marker or marker[0] >= previous_width or marker[1][0].isdigit() != ordered or (marker[1][-1] if ordered else marker[1]) != style or _thematic(lines[index].text):
                        break
                    item_begin, width = index, marker[2]
                    previous_width = width
                    current = lines[index]
                    # Width can include virtual padding; map only characters present.
                    content = current.cut(min(width, len(current.text)))
                    inner = [content]
                    index += 1
                    blank = False
                    while index < len(lines):
                        current = lines[index]
                        sibling = _list(current.text)
                        if sibling and sibling[0] < width:
                            break
                        if current.blank:
                            if len(inner) == 1 and inner[0].blank:
                                following = index
                                while following < len(lines) and lines[following].blank:
                                    following += 1
                                next_item = _list(lines[following].text) if following < len(lines) else None
                                if next_item and next_item[0] < width:
                                    index = following
                                    blank = True
                                break
                            inner.append(current)
                            blank = True
                        elif current.indent >= width:
                            inner.append(current.cut(width))
                            blank = False
                        elif not blank and not _interrupt(current) and inner and not inner[-1].blank:
                            inner.append(current)
                        else:
                            break
                        index += 1
                    next_marker = _list(lines[index].text) if index < len(lines) else None
                    if blank and next_marker and next_marker[0] < width and (next_marker[1][-1] if ordered else next_marker[1]) == style:
                        loose = True
                    children = self.blocks(inner, depth + 1)
                    if any(any(line.blank and left.span.end <= line.start < right.span.start for line in inner)
                           for left, right in zip(children, children[1:])):
                        loose = True
                    item = ListItem(*children)
                    items.append(self.locate(item, lines[item_begin].start, lines[index - 1].end))
                node = OrderedList(*items, start=int(first_marker[:-1])) if ordered else BulletList(*items)
                object.__setattr__(node, 'tight', not loose)
            else:
                paragraph = [line]
                index += 1
                level = None
                while index < len(lines) and not lines[index].blank:
                    underline = _SETEXT.match(lines[index].text)
                    if underline and not lines[index].lazy:
                        level = 1 if underline[1][0] == '=' else 2
                        index += 1
                        break
                    if _interrupt(lines[index]):
                        break
                    paragraph.append(lines[index])
                    index += 1
                text = self.inline_text(paragraph, trim=level is not None)
                node = Heading(level, text) if level else Paragraph(text)
            last = index - 1
            if isinstance(node, BulletList):
                while last > begin and lines[last].blank:
                    last -= 1
            nodes.append(self.locate(node, lines[begin].start, lines[last].end))
        return nodes


def parse_blocks(source: str, *, options: ParseOptions | None = None) -> Document:
    """Parse block structure without changing source or touching notebook state.

    Inline syntax remains Text in this phase. Unsupported syntax remains literal.
    Limits fail explicitly rather than returning a partially parsed document.
    """
    if not isinstance(source, str):
        raise TypeError('Markdown source must be a string.')
    options = options or ParseOptions()
    parser = _Parser(source, options)
    if len(source) > options.max_characters:
        parser.fail('character-limit', 'Markdown character limit exceeded.', 0, len(source))
    document = parser.locate(Document(*parser.blocks(list(_lines(source)))), 0, len(source))
    object.__setattr__(document, 'diagnostics', tuple(parser.diagnostics))
    return document
