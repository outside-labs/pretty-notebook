# Development roadmap

[GitHub Project](https://github.com/orgs/outside-labs/projects/1) tracks the
development queue. The [roadmap register](https://github.com/outside-labs/pretty-notebook/issues/81) retains the reviewed
planning context, release boundaries, source-idea coverage, and technical
references. Each task issue defines its scope, acceptance criteria, dependencies,
and planned implementation PR. Implementation PRs record the reviewed changes
and verification; current status comes from GitHub.

## Release scope

- **0.10:** 17 original required tasks plus 6 required tasks in the final
  package/appearance/deployment/coverage block, the OPS-04A startup correction,
  and 3 optional builder/operations
  tasks. Optional work can move intact to a later release.
- **0.11 foundation:** typed Markdown, CLI/operations improvements, scoped
  permissions, independent public notebook ownership and durable operation logs.
  Browser sessions, private readers/shares, remote source/history, bidirectional
  sync, browser editing and optional installed-wheel web packaging remain later work.
- **0.12 proposed:** 4 Markdown-engine tasks with explicit compatibility gates.
- **Later:** 8 follow-on tasks. Later version labels are planning buckets.

The additional 0.10 block introduces the canonical `pretty_notebook` import and
`pretty-notebook` development distribution, compatible `pnbp` imports/CLI, theme
preferences, responsive navigation, coordinated local workers, VPS bundles and
coverage auditing. Its six required child tasks are #145–#150; logging #151 is
included in 0.11. Retain local SQLite, explicitly owned public notebooks, trusted editors and a
TLS proxy, with one Gunicorn instance and up to four coordinated workers.
Release publication, hosted deployment, and new external service/provider
decisions have their own authorization boundaries.

## Ordered task index

Use the Project's Order, Target, Status, Depends on, Planned PR, and PR fields
alongside the issue scopes. Adopted tasks become Ready after their dependencies
merge. Proposed work and optional work awaiting selection remain in Triage.
Large tasks can use child issues and focused implementation PRs while retaining
the parent acceptance gate.

| Order | Task | Target |
| --- | --- | --- |
| 01 | [CFG-02: Typed settings and explicit notebook initialization](https://github.com/outside-labs/pretty-notebook/issues/63) | 0.10 required |
| 02 | [CORE-03: Separate notebook services and expose safe note commands](https://github.com/outside-labs/pretty-notebook/issues/67) | 0.10 required |
| 03 | [ID-01: Persist stable notebook and note identities](https://github.com/outside-labs/pretty-notebook/issues/69) | 0.10 required |
| 04 | [LINK-02: Rename/move notes and repair backlinks safely](https://github.com/outside-labs/pretty-notebook/issues/71) | 0.10 required |
| 05 | [DATA-01: Version server state and record publication revisions](https://github.com/outside-labs/pretty-notebook/issues/76) | 0.10 required |
| 06 | [ROUTE-01: Add hierarchical routes with legacy aliases](https://github.com/outside-labs/pretty-notebook/issues/82) | 0.10 required |
| 07 | [PUB-05: Publish by hash with checked revisions and dry-run plans](https://github.com/outside-labs/pretty-notebook/issues/83) | 0.10 required |
| 08 | [STC-02: Establish local assets and an explicit CDN policy](https://github.com/outside-labs/pretty-notebook/issues/84) | 0.10 required |
| 09 | [STC-01: Load Mermaid only on diagram pages](https://github.com/outside-labs/pretty-notebook/issues/85) | 0.10 required |
| 10 | [STC-03: Replace Bootstrap layout with project CSS](https://github.com/outside-labs/pretty-notebook/issues/86) | 0.10 required |
| 11 | [STC-04: Replace Bootstrap Icons with a small SVG set](https://github.com/outside-labs/pretty-notebook/issues/87) | 0.10 required |
| 12 | [CODE-02: Improve inline code and add accessible code tools](https://github.com/outside-labs/pretty-notebook/issues/88) | 0.10 required |
| 13 | [SEARCH-01: Add structured notebook and published-site search](https://github.com/outside-labs/pretty-notebook/issues/89) | 0.10 required |
| 14 | [WEB-06: Implement site identity and favicon management](https://github.com/outside-labs/pretty-notebook/issues/90) | 0.10 required |
| 15 | [NAV-01: Add notebook indexes, backlinks, and reading navigation](https://github.com/outside-labs/pretty-notebook/issues/91) | 0.10 required |
| 16 | [MD-01: Introduce typed Markdown builders and renderer interfaces](https://github.com/outside-labs/pretty-notebook/issues/92) | 0.10 optional |
| 17 | [OPS-02: Add reproducible deployment plans and a container profile](https://github.com/outside-labs/pretty-notebook/issues/93) | 0.10 optional |
| 18 | [OPS-03: Add deployment diagnostics and supported backup/restore commands](https://github.com/outside-labs/pretty-notebook/issues/94) | 0.10 optional |
| 19 | [DOC-02: Build versioned Sphinx documentation and tutorials](https://github.com/outside-labs/pretty-notebook/issues/95) | 0.10 required |
| 20 | [REL-04: Exercise and release the supported 0.10 surface](https://github.com/outside-labs/pretty-notebook/issues/96) | 0.10 required |
| 21 | [AUTH-02: Add explicit roles, notebook grants, and scoped credentials](https://github.com/outside-labs/pretty-notebook/issues/97) | 0.11 proposed |
| 22 | [PUB-04: Support independent notebooks and ownership-scoped pruning](https://github.com/outside-labs/pretty-notebook/issues/56) | 0.11 proposed |
| 23 | [WEB-07: Add browser sessions and an owner console](https://github.com/outside-labs/pretty-notebook/issues/98) | 0.11 proposed |
| 24 | [ACL-01: Add private reader access and protected attachments](https://github.com/outside-labs/pretty-notebook/issues/99) | 0.11 proposed |
| 25 | [SHARE-01: Add expiring, revocable note-share links](https://github.com/outside-labs/pretty-notebook/issues/100) | 0.11 proposed |
| 26 | [SRC-01: Store authoritative remote Markdown and revision history](https://github.com/outside-labs/pretty-notebook/issues/101) | 0.11 proposed |
| 27 | [SYNC-01: Add conflict-aware local/remote pull and push](https://github.com/outside-labs/pretty-notebook/issues/102) | 0.11 proposed |
| 28 | [EDIT-01: Add a trusted-author browser Markdown editor](https://github.com/outside-labs/pretty-notebook/issues/103) | 0.11 proposed |
| 29 | [PACK-01: Package the optional web app and evaluate naming aliases](https://github.com/outside-labs/pretty-notebook/issues/104) | 0.11 optional |
| 30 | [REL-05: Verify the collaboration and recovery contract](https://github.com/outside-labs/pretty-notebook/issues/105) | 0.11 proposed |
| 31 | [MD-02: Parse Markdown block structure into source-aware nodes](https://github.com/outside-labs/pretty-notebook/issues/106) | 0.12 proposed |
| 32 | [MD-03: Parse inline Markdown and render safely](https://github.com/outside-labs/pretty-notebook/issues/107) | 0.12 proposed |
| 33 | [MD-04: Implement the documented notebook dialect and extensions](https://github.com/outside-labs/pretty-notebook/issues/108) | 0.12 proposed |
| 34 | [MD-05: Complete compatibility gates and switch renderer defaults](https://github.com/outside-labs/pretty-notebook/issues/109) | 0.12 proposed |
| 35 | [PORT-01: Export portable notebooks and self-contained public sites](https://github.com/outside-labs/pretty-notebook/issues/110) | Later |
| 36 | [SITE-01: Add publication metadata, feeds, and public discovery](https://github.com/outside-labs/pretty-notebook/issues/111) | Later |
| 37 | [WEB-08: Add moderated per-note comments](https://github.com/outside-labs/pretty-notebook/issues/112) | Later |
| 38 | [INT-01: Deliver durable events through webhooks and email adapters](https://github.com/outside-labs/pretty-notebook/issues/113) | Later |
| 39 | [OBS-01: Add optional aggregate site statistics](https://github.com/outside-labs/pretty-notebook/issues/114) | Later |
| 40 | [AUTH-03: Add an optional OIDC sign-in provider](https://github.com/outside-labs/pretty-notebook/issues/115) | Later |
| 41 | [APP-01: Support validated desktop URL handlers and editor launchers](https://github.com/outside-labs/pretty-notebook/issues/57) | Later |
| 42 | [PERF-01: Optimize measured parsing and I/O bottlenecks](https://github.com/outside-labs/pretty-notebook/issues/116) | Later |

## Foundation implementation history

- Typed settings and explicit notebook initialization: [PR #64](https://github.com/outside-labs/pretty-notebook/pull/64).
- Focused notebook services, current-content views, and note commands:
  [PR #68](https://github.com/outside-labs/pretty-notebook/pull/68).
- Stable notebook/note identities: [PR #70](https://github.com/outside-labs/pretty-notebook/pull/70).
- Shared link resolution and graph diagnostics: [PR #73](https://github.com/outside-labs/pretty-notebook/pull/73).
  Journaled moves and backlink repair: [PR #75](https://github.com/outside-labs/pretty-notebook/pull/75).
- Versioned server schema upgrades: [PR #78](https://github.com/outside-labs/pretty-notebook/pull/78).
  Immutable publication revisions and legacy-page migration:
  [PR #80](https://github.com/outside-labs/pretty-notebook/pull/80).
- Filesystem-portable filename regression assertions: [PR #66](https://github.com/outside-labs/pretty-notebook/pull/66).

The released [0.9.0 baseline](https://github.com/outside-labs/pretty-notebook/releases/tag/v0.9.0) and its completed
release, dependency, and web safety gates remain in the Project history.
