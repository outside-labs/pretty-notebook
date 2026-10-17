"""Notebook-specific syntax, attributes, and stable heading anchors."""

from __future__ import annotations

import re
import bisect
import shlex
import unicodedata

from .nodes import (
    FootnoteDefinition, Paragraph, Table, TableCell, TableOfContents, TableRow,
    TaskListItem,
)


def slugify(value, separator='-'):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    value = re.sub(r'[^\w\s-]', '', value)
    return re.sub(r'[-\s]+', separator, value).strip(separator)


def attributes(value):
    """Parse an attribute list; the renderer separately decides permitted names."""
    value = value.strip()
    if not (value.startswith('{') and value.endswith('}')):
        return None
    try:
        words = shlex.split(value[1:-1].lstrip(':').strip(), comments=False)
    except ValueError:
        return None
    from .inlines import decode
    result, classes = {}, []
    for word in words:
        if word.startswith('#') and len(word) > 1:
            result['id'] = decode(word[1:])
        elif word.startswith('.') and len(word) > 1:
            classes.append(decode(word[1:]))
        elif '=' in word:
            name, content = word.split('=', 1)
            if not re.fullmatch(r'[A-Za-z_:][A-Za-z0-9_.:-]*', name):
                return None
            result[name] = decode(content)
        else:
            return None
    if classes:
        result['class'] = ' '.join(classes)
    return tuple(result.items())


def heading_attributes(value):
    match = re.search(r'[ \t]+(\{[^{}]*\})[ \t]*$', value)
    if match and (parsed := attributes(match[1])) is not None:
        return value[:match.start()].rstrip(), parsed
    return value, ()


def _cells(line):
    """Split active pipes; escapes and code delimiters keep their pipes opaque."""
    text, cells, start, fence, index = line.text, [], 0, 0, 0
    runs = {}
    for match in re.finditer(r'`+', text):
        runs.setdefault(len(match[0]), []).append(match.start())
    while index < len(text):
        if not fence and text[index] == '\\' and index + 1 < len(text):
            index += 2
            continue
        if text[index] == '`':
            end = index + 1
            while end < len(text) and text[end] == '`':
                end += 1
            length = end - index
            if fence == length:
                fence = 0
            elif not fence and bisect.bisect_right(runs.get(length, ()), index) < len(runs.get(length, ())):
                fence = length
            index = end
            continue
        if text[index] == '|' and not fence:
            cells.append((start, index))
            start = index + 1
        index += 1
    cells.append((start, len(text)))
    if cells and not text[cells[0][0]:cells[0][1]].strip():
        cells.pop(0)
    if cells and not text[cells[-1][0]:cells[-1][1]].strip():
        cells.pop()
    return cells


def special_block(parser, lines, index, depth):
    line = lines[index]
    footnote = re.match(r'^ {0,3}\[\^([^]\s]+)\]:[ \t]*', line.text)
    if footnote:
        label, begin = footnote[1], index
        inner = [line.cut(footnote.end())]
        index += 1
        while index < len(lines):
            current = lines[index]
            if current.blank:
                following = index + 1
                while following < len(lines) and lines[following].blank:
                    following += 1
                if following >= len(lines) or lines[following].indent < 4:
                    break
                inner.append(current)
            elif current.indent >= 4:
                inner.append(current.cut(4))
            else:
                break
            index += 1
        node = FootnoteDefinition(label, *parser.blocks(inner, depth + 1))
        return node, index
    if line.text.strip() == '[TOC]':
        return TableOfContents(), index + 1
    if index + 1 >= len(lines) or '|' not in line.text or line.indent >= 4:
        return None
    header, delimiters = _cells(line), _cells(lines[index + 1])
    markers = [lines[index + 1].text[left:right].strip() for left, right in delimiters]
    if not header or len(header) != len(markers) or not all(re.fullmatch(r':?-+:?', marker) for marker in markers):
        return None
    alignments = tuple('center' if marker.startswith(':') and marker.endswith(':') else 'left' if marker.startswith(':') else 'right' if marker.endswith(':') else None for marker in markers)
    def row(current, cells):
        children = []
        for left, right in cells[:len(header)]:
            text = current.text[left:right]
            left += len(text) - len(text.lstrip())
            right -= len(text) - len(text.rstrip())
            segment = current.cut(left)
            from dataclasses import replace
            segment = replace(segment, text=current.text[left:max(left, right)], positions=current.positions[left:max(left, right)], newline=None)
            text_node = parser.inline_text([segment])
            children.append(parser.locate(TableCell(text_node), text_node.span.start, text_node.span.end))
        while len(children) < len(header):
            children.append(parser.locate(TableCell(''), current.end, current.end))
        return parser.locate(TableRow(*children), current.start, current.end)
    rows = [row(line, header)]
    index += 2
    while index < len(lines) and not lines[index].blank and '|' in lines[index].text:
        rows.append(row(lines[index], _cells(lines[index])))
        index += 1
    return Table(rows[0], *rows[1:], alignments=alignments), index


def prepare_task_item(parser, item):
    if not item.children or not isinstance(item.children[0], Paragraph):
        return item
    paragraph = item.children[0]
    if not paragraph.children:
        return item
    text = paragraph.children[0]
    match = re.match(r'^\[([ xX])\][ \t]+', text.value)
    if not match:
        return item
    from dataclasses import replace
    trimmed = replace(text, value=text.value[match.end():], positions=text.positions[match.end():])
    object.__setattr__(paragraph, 'children', (trimmed, *paragraph.children[1:]))
    return TaskListItem(*item.children, checked=match[1].lower() == 'x')


def parse_notebook(source, *, options=None):
    from .inlines import parse
    return parse(source, options=options, dialect='notebook')
