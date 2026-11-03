# Markdown extraction inventory

This inventory records [source revision `2bfc586cfce7e982f73cbbb0215c99260388f73c`](https://github.com/outside-labs/pretty-notebook/tree/2bfc586cfce7e982f73cbbb0215c99260388f73c/src/pretty_notebook/markdown). It
proposes boundaries for an independent generic package; it does not move code,
select a package identity or add a dependency. The owning decision is
[Headless Spreadsheets MD-01](https://github.com/outside-labs/headless_spreadsheets/issues/11).

## Source closure

The implementation is the six files in `src/pretty_notebook/markdown/`:

| File | Existing responsibility | Extraction treatment |
| --- | --- | --- |
| `nodes.py` | Immutable builders, parsed nodes, original slices, URL validation, tables and notebook extension nodes | Move generic nodes; keep the legacy `from_component` adapter in Pretty Notebook; select extension-node ownership explicitly |
| `parser.py` | SourceSpan/SourceMap, ParseOptions, diagnostics, bounded block parsing | Move generic mechanics; replace notebook-specific dispatch with a selected dialect extension |
| `inlines.py` | Delimiters, references, entities, source positions, inline work accounting, notebook recognition | Move generic mechanics and explicit dialect dispatch; retain unresolved extension syntax and source slices |
| `dialect.py` | Pipe tables, tasks, footnotes, attributes, headings/slugging and TOC | Select a reusable opt-in dialect module; notebook link/tag/image policies remain application adapters |
| `renderers.py` | Renderer protocol, safe typed HTML, metadata and notebook context | Split generic rendering from notebook resolution/icons/routes and the legacy Python-Markdown backend |
| `__init__.py` | Public builders/parser/renderer exports | Preserve imports through compatibility re-exports during consumer migration |

The generic implementation currently needs only the standard library. No
runtime fixture files, templates or network resources are read by the parser.
The exceptions requiring an adapter are the lazy notebook imports listed below
and the explicitly optional `markdown` import in `PythonMarkdownRenderer`.
`pnbp/_rendering.py` and legacy component aliases are compatibility consumers,
not another parser to extract.

`Node.to_markdown()` uses the original half-open code-point source slice when
present. Builder serialization is deterministic but does not promise lossless
round trips for arbitrary constructed edits. Spans retain CR/LF/CRLF and
container-prefix positions. Unknown/unsupported syntax remains source text.
The extraction must not infer persistence types or rewrite notebook files.

## Notebook-owned seams

| Current seam | Concrete consumer adapter |
| --- | --- |
| `RendererContext.resolve` | Resolve wiki targets through `graph_index().resolve`, source path, publishability and configured routes; return a permitted URL or unresolved result |
| `TypedRenderer` tag handling | Apply HIDE_COMMIT_TAG/COMMIT_TAG and notebook metadata in a notebook renderer extension |
| `ImageEmbed` rendering | Supply `public_image_url` from notebook routes/config, rather than importing application routes in the generic renderer |
| External-link decorations | Supply `render_icon` from notebook icons; generic links render without application decoration |
| `nodes.from_component` | Adapt legacy CodeBlock/Link/Tag/Url values within Pretty Notebook |
| `_internal/rendering.render_note` | Select typed/legacy backend and pass current pending source, source path and explicit trusted-author policy |
| `_internal/rendering.backend_identity` | Include independent distribution/version, qualified parser/dialect/renderer identity, adapter code and selected configuration in publication fingerprints |
| Heading/diagram metadata | Preserve `RenderedMarkdown`, HeadingInfo/DiagramInfo and the notebook graph/publication consumers; generic rendering must not build notebook indexes |

The current fingerprint hashes this module and every local Markdown Python
file. Merely replacing imports would omit the new package implementation and
could leave published HTML stale. Consumer adoption must change fingerprint
inputs and qualify a cache invalidation/republication decision explicitly.

## Proposed dialect and context boundary

Keep generic `parse`, `parse_blocks`, immutable nodes/spans/diagnostics,
`ParseOptions`, `Renderer` and `TypedRenderer` in the independent surface.
Default HTML stays escaped, with URL permission separate from syntax recognition.
`trust='trusted'` is explicit verbatim HTML permission, not sanitization.

Select an immutable dialect descriptor with a versioned identity and finite
block/inline extension handlers. Handlers share the parser's existing node,
nesting and work accounting, must advance input, and return source-spanned
nodes or no match. Unknown constructs fall back to source-preserved text.
Select renderer handlers for extension nodes and a caller-owned resolution
context with no ambient notebook, file access or network. Handlers receive
explicit source path, resolver, image resolver and decoration callbacks. The
generic package must not import Pretty Notebook or silently adopt trusted HTML.
This is a proposed API for MD-01 review, not a committed plugin interface.

The existing `dialect='commonmark'/'notebook'` flags are distributed across
block parsing, inline parsing and rendering. They are not yet a reusable plugin
API. Tables are document nodes with alignment and source spans; spreadsheet
Table remains a different value with an optional display-only adapter.

Pipe table acceptance includes optional edge pipes, escaped pipes, opaque code
span pipes, alignment markers, trimmed source spans, padded short rows, ignored
overflow cells and inline markup. Notebook links, tags, footnotes, tasks, TOC,
attributes, image embeds and Mermaid need explicit compatibility fixtures.

## Limits, fixtures and provenance

The baseline supports Python >=3.11. Its syntax uses postponed annotations,
dataclasses and standard-library modules; retain 3.11 and 3.14 qualification
unless MD-01 explicitly selects another floor. Parser defaults are 2,000,000
characters, 64 levels and 100,000 nodes, with configurable lower limits and
maximum nesting 64. Inline work allows 32 steps per source character, minimum
2,000. Reference definitions admit eight physical lines, balanced destinations
32 parentheses and labels 999 characters. Limit failures raise ParseLimitError
with a diagnostic/span and return no partial document.

Carry the existing `tests/test_markdown_{builders,blocks,inlines,dialect,migration}.py`
and `tests/test_rendering.py` responsibilities to their new owners. Generic
tests need the unchanged `tests/fixtures/markdown/commonmark-blocks.json`,
`commonmark-inlines.json` and `NOTICE.md`; together the attributed corpus covers
all 652 CommonMark 0.31.2 examples. Retain block-structure, trusted raw-HTML,
URL-policy differences, malformed delimiter, ordinary/adversarial work and
source-span cases. Notebook integration tests retain actual graph/route/image,
pending-state, publication-fingerprint and legacy-backend checks.

The implementation is under this repository's MIT LICENSE; preserve its
copyright/license and record the original repository and immutable source in
the extracted package. The fixture NOTICE separately attributes John
MacFarlane's CommonMark 0.31.2 examples under CC BY-SA 4.0. Carry that notice and
license identity with fixture data; do not relabel the examples MIT. The generic
runtime needs no CommonMark data or notebook resource directory. Distribution
selection must explicitly review fixture inclusion and notices.

## Decision, migration and rollback

MD-01 still selects distribution/import/repository, ownership, MIT-compatible
provenance/notices, Python floor, public exports, dialect/extension API and
renderer/context API. After selection, create the package-owned implementation
issue and link PN-MD-EXTRACT-02. Publication remains a separate operation.

1. Copy with provenance into the selected package, preserve the generic corpus
   and budgets, and qualify isolated wheel/source installs without notebook or
   Markdown dependencies. Do not maintain two generic parser implementations.
2. Replace Pretty Notebook's generic internals with compatibility re-exports;
   retain legacy component adapters and notebook policies locally. Declare only
   the explicitly qualified optional/required dependency chosen for adoption.
3. Verify existing public imports and source spans, differential notebook HTML,
   graph metadata, pending source, URL/trust policy, table cases and fingerprints
   on supported Python versions. Run the existing strict documentation/examples
   and notebook/web acceptance before removing old generic implementation.
4. Retain a pre-adoption commit and dependency receipt. Roll back code and the
   selected dependency together; do not rewrite source Markdown or stored data.
   Recompute publication identity when switching implementations. The existing
   optional Python-Markdown backend remains its separate compatibility option,
   not an automatic fallback for parser failures.
