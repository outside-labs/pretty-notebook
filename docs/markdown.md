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
