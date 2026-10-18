# Markdown renderer migration

The 0.11 release includes the typed parser and renderer delivered by MD-01–MD-05.
The 0.10 artifacts retain the previous Python-Markdown implementation.

## Default and compatibility backend

Notebook conversion, local previews, and publication now use the in-house typed
Markdown parser and renderer. The base package and optional web deployment no
longer require Python-Markdown. Rich retains its own separate markdown-it-py
terminal-rendering dependency.

`MARKDOWN_BACKEND` accepts `typed` (default) or `python-markdown`. The same setting
works through `NotebookSettings`, notebook JSON, explicit mappings, and the
environment with normal settings precedence. To compare the old backend from a
checkout:

```bash
python -m pip install --editable '.[legacy-markdown]'
```

```python
from pretty_notebook import Notebook

native = Notebook.open("~/notes", settings={"MARKDOWN_BACKEND": "typed"})
legacy = Notebook.open("~/notes", settings={"MARKDOWN_BACKEND": "python-markdown"})
```

Selecting the compatibility backend without the optional dependency fails with
an installation hint. There is no automatic fallback. Standalone builders also
use `TypedRenderer` by default; `PythonMarkdownRenderer` remains an explicit
optional adapter.

Original Markdown remains authoritative. Parsing and rendering preserve the
source and pending edits, including when a configured parser limit fails.
Navigation outlines, graph heading validation, HTML heading IDs, and TOC links
share the same typed heading metadata and anchor allocation.

## Compatibility and intentional differences

All 652 attributed CommonMark 0.31.2 examples are checked for native rendered
output, with explicit trusted-HTML and restricted-URL policy differences.
Notebook regression fixtures run against both backends. Additional differential
fixtures compare normalized HTML structure, attributes, text and literal code;
formatting whitespace between block elements, attribute order, entity spelling,
and equivalent URL escaping are not byte-for-byte compatibility promises.

| Difference | Result in the typed backend |
| --- | --- |
| Ordered-list starts | A list beginning at `3.` retains `start="3"`. |
| List indentation/types | Two-space nesting follows CommonMark; adjacent ordered and unordered lists stay distinct. |
| Explicit heading attributes | `{#custom}` produces the same ID in rendered HTML, navigation, graph validation and TOC. The old tag preprocessor could corrupt this attribute. |
| TOC links | Local fragment links remain local and have no external-link decoration. |
| Link titles/attributes | Standard links receive consistent external-link decoration even when they have a title or attributes. |
| Unsafe URLs | Executable/unapproved schemes, obfuscated schemes, controls, backslashes and protocol-relative destinations are disabled. The original destination remains in the syntax tree. |
| Protected text | Indented code, raw HTML code blocks, fences, inline code and Mermaid are opaque to notebook extensions. Escaped wiki syntax stays literal. |
| Notebook extensions | Tables, tasks, footnotes, attributes, strike/highlight spans, wiki links, tags, image embeds, Mermaid and `nl2br` have dedicated typed fixtures. |

Standalone HTML rendering escapes raw HTML by default. Notebook conversion keeps
the existing trusted-author contract by passing an explicit trusted context.
That context allows raw HTML verbatim and is not an HTML sanitizer. All generated
text/attributes are escaped and generated destinations are validated. See the
[typed Markdown guide](markdown.md) for the context API and exact dialect rules.

## Limits and performance checks

The parser defaults to 2,000,000 source characters, 64 container/inline nesting
levels, and 100,000 allocated nodes. Inline work has a budget of 32 steps per
character (minimum 2,000). Exceeding a budget raises `ParseLimitError` with a
structured diagnostic; no partial document is returned. Reference definitions
are bounded to eight physical lines, reference labels to 999 characters, wiki
targets to 4,096 characters, and balanced destinations to 32 parentheses.
Unsupported or malformed syntax is preserved literally.

Run the reproducible workload checks from the checkout:

```bash
python scripts/check_markdown.py --legacy
```

Each workload runs in a separate process with a ten-second timeout. CI checks
ordinary 112,000-character prose, 2,000 links, 5,000 code spans, 5,000 emphasis
spans, 40,000 unmatched brackets, malformed HTML attributes and destinations,
explicit limit failures, and the repository's editing/link/code guides.

A local Python 3.14.7 macOS run completed each normal/adversarial render in
0.04–0.14 seconds; the 15,136-character guide sample took about 0.009 seconds
with the typed renderer and 0.024 seconds with the compatibility renderer.
These are reproducible observations, not a cross-machine speed guarantee.
Source, node, nesting and work budgets remain the actual input bounds.

## Publication plans

Renderer fingerprints now include the selected backend, dialect policy, and
all parser/renderer implementation modules. A backend or implementation change
invalidates a prepared checked-publication plan, even when the source has not
changed. Build a fresh plan and review its rendered changes before executing
publication. This implementation does not publish a package or deploy a site.
