# Typed Markdown

The `pretty_notebook.markdown` module composes immutable Markdown values. It is
separate from the existing string-like notebook components; production note
rendering still uses Python-Markdown.

```python
from pretty_notebook.markdown import (
    BoldText, BulletList, CodeBlock, Document, Heading, ItalicText, Link, Paragraph,
)

page = Document(
    Heading(1, "A notebook"),
    Paragraph("Read ", BoldText("this ", ItalicText("first")), ": ",
              Link("https://example.com", "reference")),
    BulletList("One", "Two"),
    CodeBlock("print('hello')\n", "python"),
)
source = page.to_markdown()
html = page.to_html()
```

Strings supplied as children become literal `Text` nodes. Punctuation and line
breaks in literal text are encoded as entities so they cannot inject Markdown
or HTML. Use block nodes for structure. `Heading` accepts levels 1–6;
`ListItem` can contain paragraphs and nested `BulletList`/`OrderedList` nodes.
`OrderedList(..., start=3)` selects its first number. `Image` accepts a
destination, literal alt text, and an optional title. Code fences grow when
their bodies contain backticks. Serialization terminates a nonempty code body
with a newline when it lacks one.

`MarkdownText` is an alias for `Document`. These are constructed values, not
parsers or complete source-location models. Their `to_markdown()` output is
deterministic, not a claim to preserve arbitrary original Markdown.

`to_html(renderer=..., context=...)` accepts the `Renderer` protocol. The
initial `PythonMarkdownRenderer` uses the same extensions as production.
`RendererContext(notebook=nb, source_path="folder/note.md", trust="escape")`
carries notebook resolution and an explicit HTML policy. Builders offer no raw
HTML node, so literal text remains escaped even with `trust="trusted"`.
Links and images accept HTTP, HTTPS, mailto, and relative destinations; unsafe
schemes, control characters, backslashes, and protocol-relative URLs fail early.

Legacy `Link`, `Tag`, `Url`, and `CodeBlock` constructors, equality, hashing,
and string output retain their existing behavior. Use `from_component(value)`
to adapt them explicitly. Wiki links resolve through the supplied notebook and
fall back to a literal label without one. No web or validation framework is
required. Block/inline parsing, notebook dialect extensions, and a backend
migration are subsequent gates in MD-02 through MD-05.

## Source-aware block parsing

`parse_blocks(source)` returns an immutable `Document` containing headings,
paragraphs, thematic breaks, fenced/indented code, block quotes, and nested
ordered/unordered lists. ATX headings require a space after their marker;
setext headings can span multiple lines. List indentation, lazy paragraph
continuations, tight/loose lists, and mixed fence lengths follow the supported
CommonMark 0.31.2 block rules. HTML comments are opaque nodes, and reference
definitions are retained for the subsequent inline phase.

Every parsed node has a `SourceSpan`: half-open Unicode code-point offsets
`start`/`end` and one-based `start_line`/`start_column` and
`end_line`/`end_column`. A nested node's span covers its original source,
including any intervening container prefixes. Inline text also retains its
character positions so later inline parsing can map around these prefixes.
`node.to_markdown()` returns that exact original slice. Parsing normalizes line
endings only in semantic values; the document preserves CR, LF, CRLF, trailing
whitespace, unknown syntax, and the original final newline. Parsing
`note.current_md` does not change the note, pending edits, files, or indexes.

Unclosed fences are valid through the end of their container and produce an
informational `Diagnostic` in `document.diagnostics`. `ParseOptions` defaults
to 2,000,000 characters, 64 container levels, and 100,000 nodes. Limit violations
raise `ParseLimitError` with an error diagnostic and source location; they never
return a partial document. Smaller limits can be supplied to `parse_blocks`.
The maximum configurable nesting limit is 64 to keep recursive traversal bounded.

The block-only entry point does not interpret inline markup or notebook
extensions. It retains HTML blocks as opaque syntax nodes. Unknown constructs remain source-preserved text.
It is not a claim of complete CommonMark conformance. The attributed official
fixtures compare block structure and code bodies; inline output has its own
acceptance gate. Parsed source uses the safe typed renderer by default. Sending original parsed
source to `PythonMarkdownRenderer` requires an explicit
`RendererContext(trust="trusted")`. Constructed builder documents retain their
existing Python-Markdown backend.

## Inline parsing and safe HTML

`parse(source)` parses both blocks and nested inline values. The inline tree
contains `Text`, `BoldText`, `ItalicText`, `Code`, `SoftBreak`, `HardBreak`,
`Link`, `Image`, and opaque `RawHtml` nodes. Brackets and delimiter runs are
resolved as nested structures; emphasis is not a sequence of regex replacements.
Backslash escapes, named/numeric entities, variable backtick delimiters,
reference definitions, collapsed/shortcut references, images, and autolinks are
supported. The original spelling and spans remain available on parsed nodes.

`document.to_html()` uses `TypedRenderer` for parsed documents. Literal text,
code, attribute values, and image alt text are escaped. HTTP/HTTPS, mailto,
relative links, and fragments are allowed. Unsafe schemes, encoded scheme
obfuscation, control characters, backslashes, and protocol-relative links render
with an empty destination. Syntax recognition is separate from URL permission:
the tree still records the original destination for inspection.

Raw HTML blocks and inline tags are syntax nodes, escaped by default. An explicit
`RendererContext(trust="trusted")` allows them verbatim, including their original
attributes. That policy is only suitable for trusted author content; it does not
sanitize arbitrary HTML. Literal builder text is always escaped under either
policy. The existing production notebook renderer is unchanged at this stage.

The attributed fixture corpus now covers all 652 CommonMark 0.31.2 examples:
block structure/code bodies and native rendered output. Raw HTML fixture output
uses the explicit trusted policy; executable/unapproved link schemes have a
separately tested rendering-policy difference. This corpus result is not a
promise of unlimited input or support for every future specification version.
Reference definitions are limited to eight physical lines, balanced destinations
to 32 parentheses, and labels to 999 characters. Inputs beyond these syntax
bounds remain literal. Inline work has a budget of 32 steps per source character
(minimum 2,000); exhausted budgets raise `ParseLimitError`. Node and nesting
limits apply to inlines as well. Long ordinary text, repeated links/code/emphasis,
and malformed delimiters have dedicated checks.
