"""Inline tokenization, bracket resolution, and nested delimiter processing."""

from __future__ import annotations

import bisect
import html
import re
import string
import unicodedata
from dataclasses import dataclass

from .nodes import (
    BoldText, Code, Container, HardBreak, Heading, Image, ItalicText, Link,
    Paragraph, RawHtml, ReferenceDefinition, SoftBreak, Text,
    FootnoteDefinition, FootnoteReference, HighlightedText, ImageEmbed,
    NotebookLink, StrikethroughText, TableCell, TagText,
)
from .parser import Diagnostic, ParseLimitError, ParseOptions, SourceMap, parse_blocks

_WIKI = re.compile(r'(!?)\[\[([^][\r\n]{1,4096})\]\]')
_FOOTNOTE = re.compile(r'\[\^([^][\s]{1,999})\]')
_ATTRIBUTES = re.compile(r'\{:[^{}\n]*\}')
_NAKED = re.compile(r'https?://[^\s<>\]\*]+')
_TAG = re.compile(r'#[A-Za-z]+(?![\w-])')
_BACKTICKS = re.compile(r'`+')
_LABEL = re.compile(r'\[((?:\\.|[^\[\]\\]){0,999})\]')
_ENTITY = re.compile(r'&(?:#[xX][0-9a-fA-F]{1,6}|#[0-9]{1,7}|[A-Za-z][A-Za-z0-9]{1,31});')
_URI = re.compile(r'<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\x00-\x20]*)>')
_EMAIL = re.compile(r'<([A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)>')
_ATTR_NAME = r'[A-Za-z_:][A-Za-z0-9_.:-]*'
_ATTR_VALUE = r'(?:"[^"\x00]*"|\'[^\'\x00]*\'|[^\s"\'=<>`\x00]+)'
_HTML = re.compile(
    r'</[A-Za-z][A-Za-z0-9-]*\s*>|<[A-Za-z][A-Za-z0-9-]*(?:\s+' + _ATTR_NAME + r'(?:\s*=\s*' + _ATTR_VALUE + r')?)*\s*/?>'
    r'|<!--(?:>|->|[\s\S]*?-->)|<\?[\s\S]*?\?>|<![A-Z][^>]*>|<!\[CDATA\[[\s\S]*?\]\]>'
)


def decode(value):
    value = re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', value)
    def entity(match):
        token = match[0]
        return html.unescape(token) if token[1] == '#' or token[1:] in html.entities.html5 else token
    return _ENTITY.sub(entity, value)


def normalize_label(value):
    return ' '.join(value.split()).casefold()


def destination(text, start, *, inline=True, spend=lambda: None):
    """Read a balanced destination and optional title; return end or no match."""
    index, size = start, len(text)
    while index < size and text[index] in ' \t\n':
        spend()
        index += 1
    if index >= size:
        return None
    begin = index
    if text[index] == '<':
        index += 1
        begin = index
        while index < size:
            spend()
            if text[index] == '\\' and index + 1 < size and text[index + 1] in string.punctuation:
                index += 2
                continue
            if text[index] == '>':
                break
            if text[index] in '<\n':
                return None
            index += 1
        if index >= size:
            return None
        url = text[begin:index]
        index += 1
    else:
        nesting = 0
        while index < size:
            spend()
            char = text[index]
            if char == '\\' and index + 1 < size and text[index + 1] in string.punctuation:
                index += 2
                continue
            if char == '(':
                nesting += 1
                if nesting > 32:
                    return None
            elif char == ')':
                if nesting == 0:
                    break
                nesting -= 1
            elif char in ' \t\n' or ord(char) < 32:
                break
            index += 1
        if nesting:
            return None
        url = text[begin:index]
    after = index
    while index < size and text[index] in ' \t\n':
        spend()
        index += 1
    title = None
    if index > after and index < size and text[index] in '\"\'(':
        closer = ')' if text[index] == '(' else text[index]
        title_start = index + 1
        index += 1
        while index < size:
            spend()
            if text[index] == '\\' and index + 1 < size and text[index + 1] in string.punctuation:
                index += 2
                continue
            if text[index] == closer:
                break
            if closer == ')' and text[index] == '(':
                return None
            index += 1
        if index >= size or re.search(r'\n[ \t]*\n', text[title_start:index]):
            return None
        title = decode(text[title_start:index])
        index += 1
        while index < size and text[index] in ' \t\n':
            spend()
            index += 1
    if inline:
        if index >= size or text[index] != ')':
            return None
        index += 1
    return decode(url), title, index


def reference_definition(lines, start):
    """Recognize a bounded reference definition before ordinary paragraph parsing."""
    available = []
    for line in lines[start:start + 8]:
        if line.blank:
            break
        available.append(line.text)
    text = '\n'.join(available)
    match = re.match(r'^ {0,3}\[((?:\\.|[^\[\]\\]){1,999})\]:[ \t]*(?:\n[ \t]*)?', text)
    if not match or not normalize_label(match[1]):
        return None
    result = destination(text, match.end(), inline=False)
    if not result:
        return None
    url, title, end = result
    if not url and not text[match.end():].lstrip().startswith('<>'):
        return None
    # Trailing content invalidates that line; a title may be on the next line.
    if end < len(text) and text[end - 1:end] != '\n' and text[end] != '\n':
        line_end = text.find('\n', match.end())
        if line_end < 0:
            return None
        fallback = destination(text[:line_end], match.end(), inline=False)
        if not fallback or fallback[2] != line_end:
            return None
        url, title, end = fallback
    used = text[:end].rstrip(' \t\n').count('\n') + 1
    return ReferenceDefinition(match[1], url, title), used


@dataclass(eq=False)
class _Token:
    node: object
    start: int
    end: int
    marker: str = ''
    can_open: bool = False
    can_close: bool = False
    previous: object = None
    following: object = None
    before: object = None
    after: object = None
    depth: int = 0


@dataclass(frozen=True)
class _AttributeMarker(Text):
    pass


class _Budget:
    def __init__(self, source, options, count):
        self.mapping, self.options = SourceMap(source), options
        self.count, self.work = count, max(2000, len(source) * 32)

    def fail(self, code, message, start=0, end=0):
        raise ParseLimitError(Diagnostic(code, message, self.mapping.span(start, end), 'error'))

    def spend(self):
        self.work -= 1
        if self.work < 0:
            self.fail('work-limit', 'Markdown inline work limit exceeded.')


class _Inline:
    def __init__(self, text, positions, budget, references, dialect='commonmark', footnotes=None):
        self.text, self.positions = text, positions
        self.budget, self.references = budget, references
        self.dialect, self.footnotes = dialect, footnotes or {}
        self.runs = {}
        for match in re.finditer(r'`+', text):
            self.runs.setdefault(len(match[0]), []).append((match.start(), match.end()))

    def make(self, node, start, end):
        self.budget.count += 1
        left = self.positions[start] if start < len(self.positions) else (self.positions[-1] + 1 if self.positions else 0)
        right = self.positions[end - 1] + 1 if end > start else left
        if self.budget.count > self.budget.options.max_nodes:
            self.budget.fail('node-limit', 'Markdown node limit exceeded.', left, right)
        object.__setattr__(node, 'span', self.budget.mapping.span(left, right))
        object.__setattr__(node, 'source', self.budget.mapping.source[left:right])
        object.__setattr__(node, 'positions', self.positions[start:end])
        return node

    def token(self, value, start, end, **kwargs):
        return _Token(self.make(Text(value), start, end), start, end, **kwargs)

    def link(self, url, children, title, image):
        # Parsed syntax can contain an unsafe URL. The renderer validates it;
        # constructed values continue to reject unsafe URLs at construction.
        if image:
            node = Image('', plain_text(children), title)
        else:
            node = Link('', *children, title=title)
        object.__setattr__(node, 'destination', url)
        return node

    def emphasis(self, tokens):
        root = _Token(None, 0, 0)
        last, delimiter = root, None
        for token in tokens:
            token.following = token.before = token.after = None
            token.previous, last.following = last, token
            last = token
            if token.marker:
                token.before = delimiter
                if delimiter:
                    delimiter.after = token
                delimiter = token
        closer = next((token for token in tokens if token.marker), None)
        bottoms = {}
        while closer:
            self.budget.spend()
            if not closer.can_close:
                closer = closer.after
                continue
            key = closer.marker, closer.can_open, (closer.end - closer.start) % 3
            bottom = bottoms.get(key)
            opener = closer.before
            while opener is not None and opener is not bottom:
                self.budget.spend()
                left, right = opener.end - opener.start, closer.end - closer.start
                odd = opener.marker in '*_' and (opener.can_close or closer.can_open) and (left + right) % 3 == 0 and (left % 3 or right % 3)
                if opener.marker == closer.marker and opener.can_open and not odd and (opener.marker in '*_' or min(left, right) >= 2):
                    break
                opener = opener.before
            if opener is None or opener is bottom:
                bottoms[key] = closer.before
                closer = closer.after
                continue
            count = 2 if min(opener.end - opener.start, closer.end - closer.start) >= 2 else 1
            children, cursor, depth = [], opener.following, 0
            while cursor is not closer:
                self.budget.spend()
                children.append(cursor.node)
                depth = max(depth, cursor.depth)
                cursor = cursor.following
            if depth + 1 > self.budget.options.max_nesting:
                self.budget.fail('nesting-limit', 'Markdown inline nesting limit exceeded.')
            kind = StrikethroughText if opener.marker == '~' else HighlightedText if opener.marker == '=' else BoldText if count == 2 else ItalicText
            node = self.make(kind(*children), opener.end - count, closer.start + count)
            middle = _Token(node, opener.end - count, closer.start + count, previous=opener, following=closer, depth=depth + 1)
            opener.following, closer.previous = middle, middle
            opener.end -= count
            closer.start += count
            opener.node = self.make(Text(opener.marker * (opener.end - opener.start)), opener.start, opener.end)
            closer.node = self.make(Text(closer.marker * (closer.end - closer.start)), closer.start, closer.end)
            # Delimiters inside a matched pair cannot match across its boundary.
            opener.after, closer.before = closer, opener
            if opener.start == opener.end:
                opener.previous.following, middle.previous = middle, opener.previous
                if opener.before:
                    opener.before.after = closer
                closer.before = opener.before
            if closer.start == closer.end:
                middle.following = closer.following
                if closer.following:
                    closer.following.previous = middle
                if closer.after:
                    closer.after.before = closer.before
                if closer.before:
                    closer.before.after = closer.after
                closer = closer.after
        result, token = [], root.following
        while token:
            result.append(token.node)
            token = token.following
        return tuple(result)

    def parse(self):
        tokens, brackets, index, size = [], [], 0, len(self.text)
        text = self.text
        while index < size:
            self.budget.spend()
            begin, char = index, text[index]
            if self.dialect == 'notebook' and (wiki := _WIKI.match(text, index)):
                index = wiki.end()
                node = ImageEmbed(wiki[2].strip()) if wiki[1] else NotebookLink(wiki[2])
                tokens.append(_Token(self.make(node, begin, index), begin, index))
            elif self.dialect == 'notebook' and (footnote := _FOOTNOTE.match(text, index)) and normalize_label(footnote[1]) in self.footnotes:
                index = footnote.end()
                node = FootnoteReference(self.footnotes[normalize_label(footnote[1])].label)
                tokens.append(_Token(self.make(node, begin, index), begin, index))
            elif self.dialect == 'notebook' and (attrs := _ATTRIBUTES.match(text, index)):
                index = attrs.end()
                tokens.append(_Token(self.make(_AttributeMarker(attrs[0]), begin, index), begin, index))
            elif self.dialect == 'notebook' and char == '#' and (tag := _TAG.match(text, index)) and (index == 0 or not re.match(r"[\\/)>\w']", text[index - 1])):
                index = tag.end()
                tokens.append(_Token(self.make(TagText(tag[0]), begin, index), begin, index))
            elif self.dialect == 'notebook' and not brackets and (bare := _NAKED.match(text, index)):
                value = bare[0].rstrip('.,;')
                excess = max(0, value.count(')') - value.count('('))
                trim = min(excess, len(value) - len(value.rstrip(')')))
                if trim:
                    value = value[:-trim]
                index += len(value)
                label = self.make(Text(value), begin, index)
                tokens.append(_Token(self.make(self.link(value, (label,), None, False), begin, index), begin, index))
            elif char == '\\' and index + 1 < size and (text[index + 1] in string.punctuation or text[index + 1] == '\n'):
                index += 2
                node = HardBreak() if text[index - 1] == '\n' else Text(text[index - 1])
                tokens.append(_Token(self.make(node, begin, index), begin, index))
            elif char == '`':
                run = _BACKTICKS.match(text, index)[0]
                runs = self.runs.get(len(run), ())
                position = bisect.bisect_right(runs, (index, size + 1))
                if position < len(runs):
                    left, end = runs[position]
                    value = text[index + len(run):left].replace('\n', ' ')
                    if value.startswith(' ') and value.endswith(' ') and value.strip(' '):
                        value = value[1:-1]
                    tokens.append(_Token(self.make(Code(value), index, end), index, end))
                    index = end
                else:
                    index += len(run)
                    tokens.append(self.token(run, begin, index))
            elif char == '&' and (match := _ENTITY.match(text, index)):
                index = match.end()
                tokens.append(self.token(decode(match[0]), begin, index))
            elif char == '\n':
                spaces = 0
                if tokens and isinstance(tokens[-1].node, Text):
                    value = tokens[-1].node.value
                    spaces = len(value) - len(value.rstrip(' '))
                    if spaces:
                        previous = tokens.pop()
                        if value.rstrip(' '):
                            tokens.append(self.token(value.rstrip(' '), previous.start, previous.end - spaces))
                        begin -= spaces
                index += 1
                node = HardBreak() if spaces >= 2 else SoftBreak()
                tokens.append(_Token(self.make(node, begin, index), begin, index))
            elif char == '<':
                auto, email = _URI.match(text, index), _EMAIL.match(text, index)
                raw = _HTML.match(text, index)
                if auto or email:
                    match = auto or email
                    url = match[1] if auto else 'mailto:' + match[1]
                    label = self.make(Text(match[1]), index + 1, match.end() - 1)
                    node = self.link(url, (label,), None, False)
                    index = match.end()
                    tokens.append(_Token(self.make(node, begin, index), begin, index))
                elif raw:
                    index = raw.end()
                    tokens.append(_Token(self.make(RawHtml(raw[0]), begin, index), begin, index))
                else:
                    index += 1
                    tokens.append(self.token('<', begin, index))
            elif char == '[' or (char == '!' and text[index:index + 2] == '!['):
                image = char == '!'
                index += 2 if image else 1
                brackets.append([len(tokens), begin, index, image, True])
                tokens.append(self.token(text[begin:index], begin, index))
            elif char == ']' and brackets:
                opening = brackets.pop()
                location, left, content_start, image, active = opening
                index += 1
                result = destination(text, index + 1, spend=self.budget.spend) if active and index < size and text[index] == '(' else None
                if result:
                    url, title, end = result
                else:
                    label, end = text[content_start:begin], index
                    explicit = _LABEL.match(text, index)
                    if explicit:
                        label = explicit[1] or label
                        end = explicit.end()
                    definition = self.references.get(normalize_label(label)) if active else None
                    if definition:
                        url, title = definition.destination, definition.title
                        result = True
                if result:
                    children = self.emphasis(tokens[location + 1:])
                    del tokens[location:]
                    node = self.link(url, children, title, image)
                    tokens.append(_Token(self.make(node, left, end), left, end))
                    index = end
                    if not image:
                        for bracket in brackets:
                            self.budget.spend()
                            if not bracket[3]:
                                bracket[4] = False
                else:
                    tokens.append(self.token(']', begin, index))
            elif char in ('*_~=' if self.dialect == 'notebook' else '*_'):
                index += 1
                while index < size and text[index] == char:
                    index += 1
                before, after = text[begin - 1:begin], text[index:index + 1]
                whitespace_before, whitespace_after = not before or before.isspace(), not after or after.isspace()
                punct_before = bool(before) and unicodedata.category(before)[0] in 'PS'
                punct_after = bool(after) and unicodedata.category(after)[0] in 'PS'
                left = not whitespace_after and (not punct_after or whitespace_before or punct_before)
                right = not whitespace_before and (not punct_before or whitespace_after or punct_after)
                can_open = left and (char != '_' or not right or punct_before)
                can_close = right and (char != '_' or not left or punct_after)
                tokens.append(self.token(text[begin:index], begin, index, marker=char, can_open=can_open, can_close=can_close))
            else:
                index += 1
                while index < size and text[index] not in ('\\`&\n<[]!*_~=#{' if self.dialect == 'notebook' else '\\`&\n<[]!*_') and not (self.dialect == 'notebook' and text.startswith(('http://', 'https://'), index)):
                    index += 1
                tokens.append(self.token(text[begin:index], begin, index))
        if tokens and isinstance(tokens[-1].node, Text) and tokens[-1].node.value.endswith(' '):
            token = tokens.pop()
            value = token.node.value.rstrip(' ')
            if value:
                tokens.append(self.token(value, token.start, token.start + len(value)))
        return self.emphasis(tokens)


def plain_text(nodes):
    return ''.join((node.target.partition('|')[2].strip() or node.target.partition('|')[0].strip().replace('#', ' > ')) if isinstance(node, NotebookLink) else node.alt if isinstance(node, Image) else node.value if isinstance(node, (Text, Code)) else '\n' if isinstance(node, (SoftBreak, HardBreak))
                   else plain_text(getattr(node, 'children', ())) for node in nodes)


def parse(source: str, *, options: ParseOptions | None = None, dialect='commonmark'):
    """Parse blocks and nested inlines, preserving every original source slice."""
    options = options or ParseOptions()
    document = parse_blocks(source, options=options, dialect=dialect)
    def walk(node):
        yield node
        for child in getattr(node, 'children', ()):
            yield from walk(child)
    nodes = tuple(walk(document))
    budget = _Budget(source, options, len(nodes))
    references = {}
    for node in nodes:
        if isinstance(node, ReferenceDefinition):
            references.setdefault(normalize_label(node.label), node)
    footnotes = {normalize_label(node.label): node for node in nodes if isinstance(node, FootnoteDefinition)}
    def visit(node):
        if dialect == 'notebook' and isinstance(node, Heading) and node.children:
            from dataclasses import replace
            from .dialect import heading_attributes
            child = node.children[-1]
            value, attrs = heading_attributes(child.value)
            if attrs:
                object.__setattr__(node, 'attributes', attrs)
                object.__setattr__(node, 'children', (*node.children[:-1], replace(child, value=value, positions=child.positions[:len(value)])))
        if isinstance(node, (Paragraph, Heading, TableCell)):
            children = []
            for child in node.children:
                if isinstance(child, Text):
                    children.extend(_Inline(child.value, child.positions or (), budget, references, dialect, footnotes).parse())
                else:
                    children.append(child)
            object.__setattr__(node, 'children', tuple(children))
        elif isinstance(node, Container):
            for child in node.children:
                visit(child)
    visit(document)
    if dialect == 'notebook':
        from .dialect import attributes
        def attach(node):
            if not isinstance(node, Container):
                return
            children = []
            for child in node.children:
                attach(child)
                if isinstance(child, _AttributeMarker):
                    attrs = attributes(child.value)
                    if attrs is not None and children and isinstance(children[-1], (Container, Image, Code)):
                        object.__setattr__(children[-1], 'attributes', attrs)
                        continue
                    child = Text(child.value, span=child.span, source=child.source, positions=child.positions)
                children.append(child)
            object.__setattr__(node, 'children', tuple(children))
        attach(document)
    return document
