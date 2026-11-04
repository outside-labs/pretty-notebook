# Local notebook navigation

Navigation is generated from the currently loaded notes, including pending
edits. It does not create index notes or record visits during ordinary lookups.
This is the local slice of [reading navigation](https://github.com/wispsy/pretty-notebook/issues/91).

```python
index = nb.navigation_index()
root = index.directory()
guides = index.directory("guides")
all_notes = index.directory(recursive=True).notes
entry = index.entry("guides/Introduction.md")
breadcrumbs = index.breadcrumbs(entry.path)
headings = index.outline(entry.path)
backlinks = index.backlinks(entry.path)
neighbors = index.neighbors(entry.path)
related = index.related(entry.path, limit=10)
```

Entries contain source name/path, title, optional note UUID, and current tags.
Titles use explicit identity metadata when available, otherwise the source
name. Directory indexes list direct notes and child directories containing
loaded notes. `recursive=True` includes descendants; empty or unloaded
directories return empty entries. Directory paths must remain inside the
notebook and outside reserved state directories. Breadcrumbs begin with the
known notebook index and end at the note.

Outlines use the same Markdown heading IDs as link diagnostics, including
explicit IDs and duplicate-heading suffixes. Notes without Markdown headings
return an empty outline. Backlinks are deduplicated and ordered by source path;
unresolved links do not invent notes. Reading neighbors follow source-name
order, with `None` at either end. Related results explain outgoing links,
incoming links, and shared tags. Explicit relationships rank first, then shared
tag counts, with source path breaking ties; the limit is 1–50. Publication,
exclusion, and generated-note control tags are ignored for shared-tag ranking.

`nb.navigation_index(public_only=True)` filters current public/exclusion tags
before generating any entries, directory names, relationships, or neighbors.
Private titles and counts are absent. It is a local projection rather than a
server authorization mechanism. All titles and heading text are plain strings;
an HTML consumer must escape them. Rebuild a snapshot after edits, a reload,
or a rename. It does not read externally changed files by itself.

Generated indexes remain separate from source notes. If a saved index note is
desired, deliberately build its Markdown from the report and save it with the
existing `nb.generate_note()` command.

## Explicit traversal history

```python
history = nb.traversal()
history.visit("guides/Introduction")
history.visit("recipes/Breakfast")
previous_note = history.back()
next_note = history.forward()
current_note = history.current
```

Each object owns its own history; `nb.get()`, search, and index reports never
append visits. Visiting the current note again does not create a duplicate.
Cycles are allowed and bounded by the history's integer `limit` (1–200,
default 200). A new visit after going Back clears the forward trail.
`back()` and `forward()` skip visits no longer available in the loaded notebook
and return `None` without moving if no available visit remains. `current` is
`None` if its note was removed. Use `nb.reload()` after external file changes.

When identities exist, history follows note UUIDs through managed renames and
moves. Without identities, it uses exact source paths; a removed path is skipped
rather than guessed. `public_only=True` limits visits and later traversal to
notes currently carrying the public tag without the exclusion tag. History
stays in memory, writes no source/state files, and is separate from browser
Back/Forward history.
