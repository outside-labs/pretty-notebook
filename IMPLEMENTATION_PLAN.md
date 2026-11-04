# Pretty-Notebook implementation roadmap

> Ordered GitHub Project / pull-request backlog, prepared 2026-10-05.
> Baseline: `main` at `681c41082e83e2df50a327024547ec64cd6f4f83`, released as `v0.9.0`.
> Product direction: portable Markdown notebooks with reliable links, useful publishing, and explicit control over sharing and synchronization.

> Tracking: all 42 cards have been transferred to the [GitHub Project](https://github.com/orgs/wispsy/projects/1) and [linked issue/PR register](https://github.com/wispsy/pretty-notebook/issues/81).
> The details below preserve the original planning snapshot. Read the linked issues and Project for current scope, dependencies, planned PRs, and completion status; [docs/roadmap.md](docs/roadmap.md) provides the task index and implementation history.

## 1. Current baseline

This plan reconciles the current repository with **Pretty-Notebook 0.10 Planning**, read in full at version 157. Proposed APIs and commands below describe intended behavior; they are not existing interfaces.

| Surface | Verified current state | Roadmap implication |
| --- | --- | --- |
| Release | `pnbp==0.9.0`; the GitHub release and publishing workflow completed successfully. | Build on the released contract rather than repeating RC work. |
| Verification | Latest main CI passed library tests, distribution checks, and web integration/deployment checks on Python 3.11 and 3.14. | Retain these checks; add feature-specific coverage with each PR. |
| Web support | One worker, one local SQLite database/data root, one notebook owning the publication namespace, trusted editors, TLS reverse proxy. | New features do not automatically approve additional workers, databases, or untrusted editors. |
| Web structure | `create_app()`, persistent storage, atomic writes, owner bootstrap, token revocation, health checks, host filtering, and contact inbox already exist. | Improve these surfaces; do not recreate them. |
| Nested notes | Recursive discovery preserves relative note paths. Publication turns `python/import.md` into the flat slug `python-import`; the server serves one slug. | Hierarchical URLs require a coordinated client/server migration. |
| Synchronization | Pages compare local and remote modification times. Existing images are normally skipped by filename. | Introduce content hashes, publication revisions, and explicit conflict checks. |
| Editing | `md_out` stages changes; `current_md` exposes pending content; saves are atomic and check for external file changes. | Preserve this safety contract while adding creation, rename, and sync workflows. |
| Rendering | Python-Markdown plus notebook extensions; Click, Rich, and Requests are also runtime dependencies. | Typed Markdown and dependency reduction are separate, measurable changes. |
| Assets | Bootstrap CSS/JS, Mermaid, and Highlight.js use CDNs; Bootstrap Icons are already local with notices. Scripts are loaded broadly. | Add asset policy and conditional loading, then replace framework CSS/icons. |
| Contact/favicon | Contact submissions persist and have an authenticated read API. `/favicon.ico` deliberately returns 404. | Build inbox management and notifications on the existing model; implement favicon upload/serving. |
| Open work | [PUB-04 #56](https://github.com/wispsy/pretty-notebook/issues/56), [APP-01 #57](https://github.com/wispsy/pretty-notebook/issues/57); no open PRs at review time. | Reuse these issue identities when implementing their scope. |

The dependency/security and web safety issues completed for 0.9 are historical work, not unfinished 0.10 gates. This snapshot is a planning review, not a new dependency audit.

## 2. Release boundaries and decisions

**0.10: better notebooks and publishing.** The required scope is configuration, stable identity, safe renames, durable publication metadata, hierarchical routes, hash-based publishing, local assets, custom CSS/icons, code presentation, search, navigation, favicon support, and documentation.

**0.10 optional:** typed Markdown builders and deployment/backup tooling. Each can ship if ready, or move intact to the next release. None should hold the required release open.

**0.11 proposed: controlled collaboration.** Add scoped permissions, multiple notebooks, browser sessions, private readers/share links, authoritative remote Markdown, conflict-aware pull/push, and a trusted-author browser editor.

**0.12 proposed: an in-house Markdown engine.** Replace Python-Markdown only after parser, extension, safety, compatibility, and performance gates pass. Version labels after 0.10 are planning buckets, not promised dates.

| Decision | Recommended contract |
| --- | --- |
| Names | Keep distribution `pnbp`, import `pnbp`, and executable `pnbp` through 0.10. Pretty-Notebook remains the product/repository name. Evaluate aliases separately in PACK-01. |
| Dependencies | Optimize for a small, justified dependency set. Keep Click, Rich, Requests, and the existing renderer until a replacement has a clear benefit and equivalent supported behavior. Zero dependencies is an option to evaluate, not a release requirement. |
| Configuration | Use a typed core settings model without requiring Pydantic in the library. Evaluate `pydantic-settings` for the optional web layer where Pydantic already exists. |
| Local state | Use `.pnbp/` for settings, identity metadata, sync state, and recoverable operation journals. Keep the notebook's existing Git repository at its normal root. |
| Identity | Persist notebook/note UUIDs separately from display names, file paths, and URLs. UUIDs identify objects; they never authorize access. |
| Markdown | Original Markdown is authoritative. HTML, search indexes, and graphs are derived outputs. Preserve unknown syntax and untouched source rather than round-tripping everything through HTML. |
| Typed components | Use structured block/inline nodes with children and eventual source spans. Keep existing string-like Link/Tag APIs compatible. Builders can arrive before a complete parser. |
| Permissions | Tags remain descriptive metadata. `#alice` and `#friends` cannot grant access. Use explicit visibility, memberships, and grants. |
| URLs | Keep existing flat URLs during migration. Introduce opt-in hierarchical routes for 0.10; use explicit notebook slugs for shared deployments later. |
| Asset policy | `auto` prefers installed local assets and permits a documented, pinned CDN fallback; `local` requires local assets and makes no CDN requests. Load Mermaid/highlighting only when needed. |
| Trust | Retain the documented trusted-editor boundary. Browser authentication/private content require a reviewed safe-rendering policy for every page sharing that origin. Comments use an independently restricted rendering policy. |
| Deployment | Preserve the one-worker/local-SQLite profile. Containers and setup commands automate that profile; scaling needs a separate support decision. |

Bootstrap is open source. Replacing it is a choice about design control, asset size, and framework coupling. Existing local icon files and any temporarily retained assets keep their applicable license notices.

## 3. Project and PR workflow

Create one issue/Project item per card and one focused implementation PR per item. Link existing issues where shown; the other IDs below are proposed identifiers, not existing GitHub issue or PR numbers.

Recommended Project fields: **Status** (Backlog, Ready, In progress, In review, Done), **Target**, **Area**, **Priority**, **Depends on**, and **PR**. Set a card Ready only when its dependencies have merged and its acceptance criteria are clear. Use the order below to choose the next unblocked card.

Branch examples: `feat/ID-01-note-identities`, `fix/WEB-06-favicon`, `docs/DOC-02-sphinx`. Use Conventional Commits. Carry implementation, focused tests, and relevant user documentation in the same PR; keep current progress in the issue/Project and PR.

A large card is a parent work item: split migration, API, and UI work into child PRs when they cannot be reviewed comfortably together. Preserve its acceptance gate and dependency order. In particular, LINK-02, DATA-01, PUB-04, ACL-01, EDIT-01, and the parser cards may require such splits.

**Shared done criteria:** preserve existing supported behavior or document/test its migration; run the affected tests and existing relevant CI checks; include failure-path tests for writes, permissions, and synchronization; update examples for changed APIs. A documentation-only change needs document validation and the repository's normal checks.

## 4. Ordered PR register

The three optional 0.10 cards appear before documentation/release so they can be included if selected. Defer them without blocking REL-04.

| Order | Card / proposed PR title | Target | Depends on |
| --- | --- | --- | --- |
| 01 | CFG-02 — Typed settings and explicit notebook initialization | 0.10 required | — |
| 02 | CORE-03 — Separate notebook services and expose safe note commands | 0.10 required | CFG-02 |
| 03 | ID-01 — Persist stable notebook and note identities | 0.10 required | CORE-03 |
| 04 | LINK-02 — Rename/move notes and repair backlinks safely | 0.10 required | ID-01 |
| 05 | DATA-01 — Version server state and record publication revisions | 0.10 required | CFG-02, ID-01 |
| 06 | ROUTE-01 — Add hierarchical routes with legacy aliases | 0.10 required | LINK-02, DATA-01 |
| 07 | PUB-05 — Publish by hash with checked revisions and dry-run plans | 0.10 required | DATA-01, ROUTE-01 |
| 08 | STC-02 — Establish local assets and an explicit CDN policy | 0.10 required | CFG-02 |
| 09 | STC-01 — Load Mermaid only on diagram pages | 0.10 required | STC-02, PUB-05 |
| 10 | STC-03 — Replace Bootstrap layout with project CSS | 0.10 required | STC-02 |
| 11 | STC-04 — Replace Bootstrap Icons with a small SVG set | 0.10 required | STC-03 |
| 12 | CODE-02 — Improve inline code and add accessible code tools | 0.10 required | STC-02, STC-03 |
| 13 | SEARCH-01 — Add structured notebook and published-site search | 0.10 required | DATA-01, ROUTE-01, STC-03 |
| 14 | WEB-06 — Implement site identity and favicon management | 0.10 required | DATA-01, STC-03 |
| 15 | NAV-01 — Add notebook indexes, backlinks, and reading navigation | 0.10 required | LINK-02, ROUTE-01, SEARCH-01 |
| 16 | MD-01 — Introduce typed Markdown builders and renderer interfaces | 0.10 optional | CORE-03 |
| 17 | OPS-02 — Add reproducible deployment plans and a container profile | 0.10 optional | CFG-02, DATA-01, STC-02 |
| 18 | OPS-03 — Add deployment diagnostics and supported backup/restore commands | 0.10 optional | OPS-02 |
| 19 | DOC-02 — Build versioned Sphinx documentation and tutorials | 0.10 required | Required 0.10 feature cards |
| 20 | REL-04 — Exercise and release the supported 0.10 surface | 0.10 required | DOC-02 |
| 21 | AUTH-02 — Add explicit roles, notebook grants, and scoped credentials | 0.11 proposed | DATA-01 |
| 22 | PUB-04 — Support independent notebooks and ownership-scoped pruning | 0.11 proposed | AUTH-02, PUB-05, ROUTE-01 |
| 23 | WEB-07 — Add browser sessions and an owner console | 0.11 proposed | AUTH-02, PUB-04, STC-03 |
| 24 | ACL-01 — Add private reader access and protected attachments | 0.11 proposed | PUB-04, WEB-07 |
| 25 | SHARE-01 — Add expiring, revocable note-share links | 0.11 proposed | ACL-01 |
| 26 | SRC-01 — Store authoritative remote Markdown and revision history | 0.11 proposed | PUB-04, ACL-01 |
| 27 | SYNC-01 — Add conflict-aware local/remote pull and push | 0.11 proposed | SRC-01, PUB-05 |
| 28 | EDIT-01 — Add a trusted-author browser Markdown editor | 0.11 proposed | SYNC-01, WEB-07, ACL-01 |
| 29 | PACK-01 — Package the optional web app and evaluate naming aliases | 0.11 optional | OPS-02, DOC-02 |
| 30 | REL-05 — Verify the collaboration and recovery contract | 0.11 proposed | PUB-04, WEB-07, ACL-01, SHARE-01, SYNC-01, EDIT-01 |
| 31 | MD-02 — Parse Markdown block structure into source-aware nodes | 0.12 proposed | MD-01, DOC-02 |
| 32 | MD-03 — Parse inline Markdown and render safely | 0.12 proposed | MD-02 |
| 33 | MD-04 — Implement the documented notebook dialect and extensions | 0.12 proposed | MD-03 |
| 34 | MD-05 — Complete compatibility gates and switch renderer defaults | 0.12 proposed | MD-04, LINK-02, CODE-02 |
| 35 | PORT-01 — Export portable notebooks and self-contained public sites | Later | ID-01, ROUTE-01, STC-02 |
| 36 | SITE-01 — Add publication metadata, feeds, and public discovery | Later | SEARCH-01, NAV-01, ACL-01 |
| 37 | WEB-08 — Add moderated per-note comments | Later | ACL-01, WEB-07 |
| 38 | INT-01 — Deliver durable events through webhooks and email adapters | Later | DATA-01, WEB-07 |
| 39 | OBS-01 — Add optional aggregate site statistics | Later | CFG-02, ACL-01 |
| 40 | AUTH-03 — Add an optional OIDC sign-in provider | Later | AUTH-02, WEB-07 |
| 41 | APP-01 — Support validated desktop URL handlers and editor launchers | Later | CFG-02, ID-01 |
| 42 | PERF-01 — Optimize measured parsing and I/O bottlenecks | Later | PUB-05, SEARCH-01 |

## 5. 0.10 implementation cards

### CFG-02 — Typed settings and explicit notebook initialization

Add an explicit path/settings API, proposed as `Notebook(path=..., settings=...)` and `Notebook.open(path)`, while preserving `Notebook()` environment-based use. Ordinary library construction must not prompt. Move settings generation to `pnbp init`; introduce `.pnbp/settings.json` and named local notebook profiles.

- Specify precedence: explicit arguments > environment > selected settings file > defaults; retain `PNBP_SETTINGS=off` behavior and validate known values.
- Provide a previewable migration from `pnbp_settings.json`; refuse ambiguous simultaneous configurations.
- Separate token/secret storage from portable configuration, redact diagnostics, and retain restrictive secret-file permissions.
- Skip `.pnbp/` during every note-discovery mode. Do not move or initialize Git implicitly.

**Accept:** legacy and explicit-path fixtures load identically; invalid settings fail clearly; construction is noninteractive; migration is repeatable and preserves the original until verified.

### CORE-03 — Separate notebook services and expose safe note commands

Extract settings loading, note storage, rendering, search, and the HTTP publishing client from the long constructor/class into focused internal modules. Keep Notebook as the convenient public facade; avoid a wholesale model rewrite.

- Add `pnbp note add/show/edit` and notebook-profile selection using existing creation/save operations.
- Document `md`, `md_out`, `current_md`, save/discard, and the returned saved Note instance precisely.
- Make derived current-content views explicit and invalidate their caches when pending text changes; retain compatible legacy fields.
- Replace implicit command discovery where practical with explicit registration under the existing Click CLI. Add bounded, redacted JSON output for search/status/dry-run consumers.

**Accept:** existing CLI/API regression tests still pass; adding a note never overwrites silently; pending edits survive reads/rendering; external file changes still prevent stale saves.

### ID-01 — Persist stable notebook and note identities

Introduce a versioned `.pnbp/metadata.json` index with notebook UUID, note UUIDs, relative paths, and optional title/aliases/route metadata. Plain Markdown remains readable without this file.

- Create identity state through explicit init/migration, not read-only discovery.
- Define clone versus fork behavior and provide an explicit way to fork identities.
- Detect duplicate IDs and ambiguous external renames. Hash matches may suggest reconciliation, but cannot prove identity when two notes have identical content.
- Preserve IDs through supported rename/move commands and export. Keep credentials out of metadata.

**Accept:** restart and supported moves preserve identity; copying identical note contents does not merge their identities; corrupt or missing metadata produces a recoverable diagnostic.

### LINK-02 — Rename/move notes and repair backlinks safely

Add a shared resolver, a graph index, `nb.rename_note(...)` / `nb.move_note(...)`, and CLI equivalents. Produce a dry-run showing changed files, link replacements, and proposed URL aliases.

- Update matching wiki targets while preserving labels, heading fragments, surrounding source, and literal code.
- Specify relative-path versus notebook-root link resolution; report ambiguous basename links and broken/unknown heading targets.
- Revalidate source contents and destinations before writes. Journal multi-file changes so failure or restart can roll back or resume without losing originals.
- Connect title/aliases and stable IDs to graph lookup; never replace arbitrary matching prose.

**Accept:** nested duplicate basenames, case-only renames, aliases, code literals, interrupted writes, and externally edited backlinks are covered. Failed operations leave a documented recovery path; a dry-run changes no files.

### DATA-01 — Version server state and record publication revisions

Replace startup-only schema generation as an upgrade strategy with versioned migrations. Introduce a publication catalog: notebook/note IDs, canonical route, aliases, title, visibility, source hash, rendered hash, renderer fingerprint, feature flags, and revision.

- Keep the initial catalog bound to one default notebook under the existing support profile.
- Import legacy flat pages without treating their HTML as executable Jinja; missing source Markdown remains explicitly unknown.
- Store new bodies as immutable blobs and atomically select the current revision in SQLite. Write a complete blob before committing its pointer; failed database work must leave the previous head usable.
- Record migration backup/version and provide recovery instructions. Collect orphan blobs only when no revision references them.

**Accept:** migrations from representative 0.9 state preserve accounts, token state, messages, routes, and page bodies; failures between blob and catalog writes never expose missing/partial current content.

This supplies prerequisites for PUB-04; it does not close issue #56 or approve shared pruning.

### ROUTE-01 — Add hierarchical routes with legacy aliases

Separate note identity, file path, display title, and public route. Proposed opt-in mapping: `python/function-definitions.md` → `/python/function-definitions`. Keep existing flat routes working as aliases when unambiguous.

- Validate each segment; reject traversal, encoded separators, invalid/empty segments, reserved prefixes, and route collisions before publication.
- Define an explicit route override for names that cannot produce a usable slug; avoid silently dropping an entire non-ASCII title.
- Register fixed/API routes ahead of the path catch-all. Preserve real 404 responses for absent notes.
- Render links and images with root-absolute or configured-prefix URLs. Prepare a route mode for `/n/<notebook-slug>/...` without yet enabling independent notebooks.

**Accept:** nested reads, heading links, redirects, URL-prefix deployments, reserved paths, and collision failures are tested. Migration previews identify flat-name collisions and never overwrite another page.

### PUB-05 — Publish by hash with checked revisions and dry-run plans

Hash exact source bytes and image bytes. Define a renderer fingerprint from version and output-affecting settings; compute the actual HTML digest. Server revisions/strong ETags are the concurrency authority, not client clocks or submitted UUIDs.

- Negotiate API capabilities; keep a clearly documented legacy 0.9 mode during transition.
- Return structured create/update/unchanged/delete/conflict plans. Dry-run may read the remote inventory but must not write remote or local state.
- Require checked revisions for new update/delete operations; compare and update inside the server transaction. Use `If-Match` and return `412` for a stale representation; keep semantic collisions distinct.
- Persist sync state only after success. Retain preflight, explicit prune, default page preservation, and stop-before-prune behavior.
- Refresh images by content, and regenerate unchanged Markdown when renderer settings change. Bind a plan to its notebook, target, and expected revisions.

**Accept:** equal timestamps with changed bytes publish; newer timestamps with identical bytes skip; renderer changes regenerate; stale concurrent updates fail without overwriting; retries after partial failure are safe. Shared ownership still waits for PUB-04.

### STC-02 — Establish local assets and an explicit CDN policy

Create an asset manifest with reviewed versions, paths, integrity data, and applicable notices. Supply local runtime assets through the reviewed deployment/build flow; Python runtime installation must not require Node.

- Support `auto` local-first behavior and an explicit pinned CDN fallback, plus strict `local` mode.
- Validate installed assets at startup/deployment. Missing required local assets produce a useful error in strict mode.
- Serve immutable/versioned assets with suitable cache headers and define script/style security policy.
- Retain Bootstrap temporarily until STC-03/STC-04 finish; manage Highlight.js/Mermaid through the same resolver.

**Accept:** a representative local-mode site renders with external networking blocked; mixed/missing-asset fixtures follow the declared policy; notices match retained assets.

### STC-01 — Load Mermaid only on diagram pages

Use publication feature metadata to mark pages containing Mermaid fences. Handle legacy pages with a bounded DOM-based detection fallback; do not load Mermaid on home/search/contact/plain-note pages without diagrams.

- Use the asset resolver, local-first plus documented CDN fallback.
- Validate theme options, use a restrictive Mermaid security mode, and display source text when rendering cannot complete.
- Reinitialize safely for theme/navigation changes without duplicate rendering.
- Keep ordinary code blocks independent of diagram execution.

**Accept:** network/browser checks show zero Mermaid requests on plain pages; local and CDN modes each render a diagram; oversized/malformed diagrams fail without breaking navigation.

### STC-03 — Replace Bootstrap layout with project CSS

Create a compact CSS system for typography, spacing, color, buttons, forms, tables, responsive navigation, code, and light/dark themes. Use semantic HTML, a real flex/grid footer, and the Outside Labs branding controls.

- Remove the current fixed 650px footer spacer.
- Convert shared/home/contact templates and define reusable classes for later search/console screens.
- Preserve supported generated content with a documented migration or small transitional compatibility styles.
- Replace only the JavaScript interactions the site uses; remove Bootstrap CSS/JS once all current templates are converted.

**Accept:** keyboard navigation, visible focus, error states, narrow screens, long titles, reduced motion, contrast, and light/dark pages are checked. Plain content stays readable without JavaScript.

### STC-04 — Replace Bootstrap Icons with a small SVG set

Inventory the icons actually used and replace them with a minimal project-owned or appropriately licensed SVG set.

- Expose a consistent template helper with size/style controls and accessible names.
- Use text labels where an icon alone would be ambiguous.
- Remove the Bootstrap icon font/CSS only after every usage is migrated; retain relevant notices for anything still shipped.

**Accept:** all current actions remain understandable and keyboard accessible; removed font files are absent from runtime requests; no unrelated icon framework is introduced.

### CODE-02 — Improve inline code and add accessible code tools

Style inline code separately from fenced blocks. Add an optional language label and copy button to code blocks, using a small local script and conditional Highlight.js loading.

- Copy original code text rather than highlighted HTML; keep language names escaped.
- Preserve indentation, Unicode, trailing newlines, long lines, and code containing notebook syntax.
- Provide an announced success/failure state and a useful no-JavaScript experience.
- Keep highlighting optional; replacing Highlight.js is not necessary to remove Bootstrap.

**Accept:** copied bytes/text match the fixture's code; unknown languages and clipboard failures degrade cleanly; code labels and controls work with keyboard and screen-reader semantics.

### SEARCH-01 — Add structured notebook and published-site search

Introduce a quiet `nb.search(...)` returning typed hits while retaining `nb.find(regex)` compatibility. Add CLI and web title/content/tag filters, excerpts, pagination, and deterministic ordering.

- Default to literal search. Keep regex an explicit local option, not a public query language.
- Build a derived index from the publication catalog; choose bounded simple search first or SQLite FTS after verifying platform support.
- Limit query/result sizes and escape excerpts. Search only currently published public content in 0.10.
- Design the query boundary so later permission filtering happens before snippets, counts, and ranking are returned.

**Accept:** stale/deleted/private notes are excluded from the public index; punctuation and Unicode work; pagination is stable; malicious markup is escaped; local regex errors are reported clearly.

### WEB-06 — Implement site identity and favicon management

Add configured page/site titles and a dedicated authenticated favicon upload/update operation. Start with the already supported PNG format; additional formats need their own validation.

- Persist the validated favicon in the data root, expose a correct image response, and add the head link.
- Make `/favicon.ico` serve or redirect to the configured asset deliberately; missing state remains 404.
- Restrict management to the appropriate site-management permission once roles arrive; document the POST request and client command.
- Use content-versioned URLs/cache invalidation after replacement.

**Accept:** upload, replace, restart, invalid image, anonymous upload, and missing favicon behaviors are tested; a browser observes the replacement without a stale cache.

### NAV-01 — Add notebook indexes, backlinks, and reading navigation

Add generated notebook/directory indexes, breadcrumbs, a heading outline, backlinks, deterministic previous/next, and an optional related-notes panel.

- Prefer explicit link relationships and shared tags for explainable related results; embeddings are not required.
- Keep generated indexes separate from source notes unless an explicit command saves them.
- Use normal browser history for Back; provide a known notebook/index fallback for direct visits.
- Offer a separate opt-in local traversal-history object and `back()/forward()` behavior; ordinary lookups do not secretly record visits.

**Accept:** cycles, missing headings, empty directories, renamed notes, direct-entry Back, and unpublished neighbors behave predictably; generated public navigation never exposes private titles or counts.

### MD-01 — Introduce typed Markdown builders and renderer interfaces

**Optional for 0.10.** Add composable document/block/inline builders and a renderer protocol. Begin with Text, BoldText, ItalicText, Heading, Paragraph, lists, Link, Image, and CodeBlock; document subsequent nodes in MD-02–MD-04.

- Implement `MarkdownText`/Document composition and `to_markdown()`; provide `to_html()` through a renderer context carrying notebook resolution and trust policy.
- Keep the existing Python-Markdown-backed production renderer.
- Preserve current Link/Tag/Url/CodeBlock construction/equality; introduce adapters rather than silently changing their string behavior.
- Do not claim that builders parse all existing Markdown or provide complete source spans.

**Accept:** constructed nested examples render deterministically through the current backend; literal text is escaped according to policy; importing the core does not add Pydantic or web dependencies.

### OPS-02 — Add reproducible deployment plans and a container profile

**Optional for 0.10.** Extend the existing app factory/configuration rather than replacing it. Add a reviewed container and proposed `pnbp deploy plan/init/check` operations for the supported Linux profile.

- Generate service, reverse-proxy, environment-template, persistent-volume, and asset setup instructions from a pinned release.
- Separate preview from apply; never overwrite an existing secret/state root or claim owner bootstrap automatically.
- Make reruns idempotent. Bind the app to loopback/private container networking and keep exactly one worker.
- Cover upgrades, migrations, health checks, and rollback; make platform-specific requirements explicit.

**Accept:** clean-host/container smoke tests exercise the documented setup; reruns preserve state; failed setup leaves understandable recovery steps. This PR does not expand the worker/platform support matrix.

### OPS-03 — Add deployment diagnostics and supported backup/restore commands

**Optional for 0.10.** Add `pnbp doctor` and web deployment checks, plus previewable stopped-site backup/restore operations.

- Check settings, paths/permissions, package/API compatibility, local assets, migrations, and health without revealing tokens.
- Back up the complete SQLite/files/settings state and record the matching code version.
- Restore into a new state location, verify it, then switch deliberately; preserve the failed/original state.
- Use bounded JSON/text diagnostics. Keep development test execution in the repository; do not turn runtime `commands/test` into a second test framework.

**Accept:** a fresh restored instance retains pages, images, users/revocation state, layout, and inbox; a version mismatch or incomplete backup refuses activation.

### DOC-02 — Build versioned Sphinx documentation and tutorials

Introduce Sphinx with MyST for existing Markdown and targeted API/CLI reference generation. Configure Read the Docs; use wispsy.com as the project landing page or a clearly directed documentation entry point.

- Cover first notebook, pending edits/save, add/rename, links/routes, publishing/dry-run, local assets, search/navigation, and deployment.
- Publish current and versioned documentation with one canonical URL; avoid maintaining divergent copies.
- Keep docs/build dependencies out of the runtime library.
- Update all optional-feature examples only for cards actually included in the release.

**Accept:** a clean docs build passes warnings-as-errors and internal-link checks; runnable examples use the supported package/API; README/PyPI/deployment references agree.

### REL-04 — Exercise and release the supported 0.10 surface

Release the required scope; optional cards are either verified and listed or explicitly deferred.

- Run existing library/web checks and installed-wheel/package checks.
- Exercise a notebook migration, rename with backlinks, flat-to-hierarchical route migration, hash/image updates, search/navigation, and local-only assets.
- Restore representative upgraded server state and check legacy-client behavior.
- Record the exact supported topology and deferred features in release notes.
- Publish an RC, exercise it, then complete the existing protected final-release flow.

**Accept:** a fresh install and a documented 0.9 upgrade both pass the representative workflow; no pending data-loss, migration, or publication-conflict defect remains; release metadata, artifacts, docs, and support statements agree.

## 6. Controlled collaboration cards

### AUTH-02 — Add explicit roles, notebook grants, and scoped credentials

Separate owner/site administration, notebook editing/publishing, inbox access, and reader access. Add narrow API credential scopes suitable for scripts; a UUID or username is never sufficient permission.

**Accept:** deny-by-default checks cover every read/write route; owner bootstrap/revocation survive migration; existing trusted-editor accounts have an explicit reviewed migration; readers cannot access layout, inbox, publishing, or another notebook.

### PUB-04 — Support independent notebooks and ownership-scoped pruning

Continue [issue #56](https://github.com/wispsy/pretty-notebook/issues/56). Persist notebook ownership and explicit notebook slugs, bind publications/attachments to their owners, and scope inventories/deletion to the authenticated grant.

**Accept:** two notebooks with identical note names coexist; restart and partial upload retain ownership; A cannot overwrite/delete/prune B's state; legacy unscoped prune endpoints cannot bypass the new boundary. Close #56 only when the shared-site contract and migrations are verified.

### WEB-07 — Add browser sessions and an owner console

Build sign-in/out, account/notebook administration, publication status, and contact-inbox views with pagination, read/archive/delete, and configurable retention. Use server-controlled sessions with secure cookies, CSRF protection, expiration, and logout/revocation.

Before enabling sessions, implement a reviewed rendering/CSP policy across the origin or isolate legacy trusted HTML on a separate public origin. HttpOnly cookies alone do not make arbitrary same-origin page scripts safe.

**Accept:** login/session expiry/logout, CSRF rejection, permission boundaries, token changes, inbox failures, and escaped message display are tested. All HTML paths reachable by an authenticated browser meet the chosen trust contract.

### ACL-01 — Add private reader access and protected attachments

Implement public, unlisted, and private visibility explicitly. Unlisted means excluded from discovery; it does not replace authorization. Add notebook groups/memberships and per-note grants, with deny rules taking precedence.

Move protected content/attachments behind authorization-aware routes; the current unrestricted image mount cannot serve private images. Define migration from the old public static URLs.

**Accept:** private titles, bodies, tags, snippets, graph edges, images, counts, feeds, and navigation do not leak through any public view or cache; deleted membership/revoked sessions lose access; cached responses vary or are disabled appropriately.

### SHARE-01 — Add expiring, revocable note-share links

Create high-entropy, hashed-at-rest capabilities bound to a note/revision or clearly defined live note. Add expiration, revocation, optional use limits, restricted permissions, and covered attachment access.

Exchange URL capabilities for short-lived scoped access where possible; keep tokens out of referrers, analytics, and ordinary request logs.

**Accept:** expiry/revocation work immediately; links cannot enumerate sibling notes or grant editing; attachments use the same restriction; access-limit races and capability leakage paths are covered.

### SRC-01 — Store authoritative remote Markdown and revision history

Add original Markdown to versioned server revisions, alongside derived HTML. Store author, base revision, timestamps, route/visibility metadata, and attachment references. Add list/read/diff/revert endpoints with bounded history and retention.

**Accept:** 0.9 HTML-only pages remain source-unknown rather than being converted back into invented Markdown; authorized revisions are recoverable; failed source/render writes do not advance the current head; history and tombstones obey permissions.

### SYNC-01 — Add conflict-aware local/remote pull and push

Persist the last common source/revision as the sync base. Distinguish unchanged, local-only, remote-only, simultaneous changes, and deletion conflicts. Preview before apply; preserve unsaved local edits.

Use a conservative three-way text merge only when unambiguous. Store conflicting variants/recovery files and require an explicit choice; never silently take last-writer-wins or execute conflict-marker text as a resolved publication.

**Accept:** offline edits, clock skew, renames, both-side edits/deletes, missing attachments, interrupted pulls, and retries preserve recoverable content. Sync bookkeeping advances only after confirmed successful application.

### EDIT-01 — Add a trusted-author browser Markdown editor

Build an accessible Markdown textarea/editor first, with safe preview, explicit Save, revision-aware conflicts, draft/published state, recoverable autosave, attachments, and history. Keep the preview renderer consistent with CLI publishing.

**Accept:** edits are original Markdown; expired sessions and network loss preserve the draft; stale saves cannot overwrite concurrent edits; pending autosaves do not become public; private attachments/preview obey ACLs. Untrusted collaborative authors remain a separately reviewed feature.

### PACK-01 — Package the optional web app and evaluate naming aliases

**Optional.** Choose a supported package boundary so a web extra includes executable server code, templates, and assets, not just dependencies for an unpackaged `apps/web` directory. A likely design is a lazy-imported `pnbp.web` package with repository wrappers preserving established deployment commands.

Evaluate `pretty-notebook` distribution/CLI and `pretty_notebook` import aliases only with a migration rationale and current name-availability checks. Avoid maintaining two divergent implementations or taking a name with an empty placeholder release.

**Accept:** installed wheels run the server without a checkout; core imports do not load FastAPI; optional dependencies and resources are complete; old imports/commands remain supported or have an explicit tested transition.

### REL-05 — Verify the collaboration and recovery contract

Exercise two independently owned notebooks, scoped writers/readers, private images/search, revoked shares, source history, interrupted sync, and concurrent browser/local edits. Restore a complete upgraded deployment and repeat permission checks.

**Accept:** define exactly which collaboration features ship, including their safe-rendering boundary. Retain the single-worker/SQLite profile unless separate evidence approves expansion. Defer incomplete feature cards rather than exposing partial permissions.

## 7. In-house Markdown engine cards

A parser is a separate implementation project. Typed builders do not by themselves replace Python-Markdown, and CommonMark compatibility does not cover all currently enabled extensions.

### MD-02 — Parse Markdown block structure into source-aware nodes

Define the supported dialect, grammar fixtures, and source-span/diagnostic API. Implement Document/MarkdownText, Paragraph, Heading levels 1–6 including setext rules, thematic breaks, fenced/indented code, blockquotes, and ordered/unordered nested lists.

**Accept:** official-spec cases for supported rules, incomplete Markdown, nested blocks, line endings, and long inputs pass; untouched source is preserved; parsing does not mutate Note state. Record unsupported syntax and complexity limits explicitly.

### MD-03 — Parse inline Markdown and render safely

Implement Text, BoldText/Strong, ItalicText/Emphasis, inline Code, soft/hard breaks, Links/reference links, Images, and escaping. Use nested nodes with spans, not sequential regex replacement of bold/italic markers.

**Accept:** delimiter nesting, intraword underscores, variable code delimiters, entities, labels/destinations, and malformed syntax pass fixtures. Escape text/attributes, validate URL schemes, and define raw-HTML handling separately from syntax. Safe rendering of untrusted content can use a maintained sanitizer where needed.

### MD-04 — Implement the documented notebook dialect and extensions

Add StrikethroughText, highlighted text, Tables, task-list items, Footnotes, attribute-list compatibility, heading IDs/TOC, wiki links, tags, image embeds, and Mermaid nodes. Preserve or explicitly migrate the current `nl2br` behavior.

Use notebook resolution and the graph index for link rendering. Expose structured heading/language/diagram metadata for navigation and assets.

**Accept:** existing renderer and protected-text regression fixtures pass; real notebook examples cover all currently used extensions; heading IDs/aliases and link resolution are consistent across CLI, preview, and published pages.

### MD-05 — Complete compatibility gates and switch renderer defaults

Run differential comparisons against the existing renderer and the documented dialect fixtures; classify intentional differences. Measure representative notebooks and adversarial long inputs. Switch behind an explicit backend setting before changing the default.

**Accept:** supported syntax has complete fixtures; source preservation, literal code, URL/HTML safety, failures, and bounded performance meet documented criteria. Remove Python-Markdown from runtime requirements only after the default backend passes these gates and migration notes/examples are ready. Keep it in development tests if still useful.

If implemented as a separate reusable package, publish and depend on that package explicitly rather than embedding hidden copies. Preserve license notices for any borrowed test corpus or code.

## 8. Valuable follow-on feature cards

### PORT-01 — Portable notebook and self-contained public-site export

Export original Markdown, identity metadata, attachments, and a manifest; separately export the public HTML site with local assets and working prefix-relative links. Add machine-readable graph/search export for external tools, including potential Backpack adapters.

**Accept:** restore/export round trips preserve IDs and source; archives exclude credentials, pending drafts, private notes, and restricted attachments by default; offline public-site fixtures navigate successfully. No integration package becomes a required dependency.

### SITE-01 — Publication metadata, feeds, and public discovery

Add explicit title, description, publication/update dates, canonical URLs, sitemap, and a selected feed format. Optional author attribution, a reading outline, and predictable pagination support a notebook that also works as a blog.

**Accept:** draft/private/unlisted policy is consistent across feeds, sitemap, previews, search, and routes; rename aliases preserve canonical URLs; generated metadata is escaped. Do not infer publication dates from incidental file copying.

### WEB-08 — Moderated per-note comments

Associate comments with stable note IDs, store plain text or a restricted Markdown subset, and provide pending/approved/rejected/deleted states. Start with simple comments; add threads only if usage justifies them.

**Accept:** permissions, moderation, rate limits, duplicate submission behavior, escaped rendering, retention, and removal are tested. Readers cannot insert owner HTML or execute scripts. Contact messages stay private and are not reused as comments.

### INT-01 — Durable events, webhooks, and email adapters

Add a transactional outbox for selected events such as contact submission, approved comment, publication, and share revocation. Persist the event with the underlying action, then dispatch using a bounded recoverable task under the supported process profile.

**Accept:** signed HTTPS webhook requests, secret redaction, destination validation, timeouts, retry limits, idempotency IDs, and failed-delivery status are covered. Delivery failure never discards a stored message. Recheck DNS/redirect destinations to prevent requests into private services; adapters remain optional.

### OBS-01 — Optional aggregate site statistics

Provide coarse page-view totals and request/error summaries with explicit opt-in, bounded retention, and query/report methods. Separate security/session records from public-site analytics.

**Accept:** disabling statistics performs no analytics writes; do not store raw capability URLs or private content; aggregate visits without durable cross-site identity. If unique-visitor/session analysis is later wanted, define its data/retention contract as a separate extension.

### AUTH-03 — Optional OIDC sign-in

Add a standards-based provider adapter using a maintained authentication library, with authorization-code/PKCE, state/nonce validation, account-linking controls, and a local recovery path.

**Accept:** external identity does not automatically grant notebook rights; duplicate-email/account-linking attacks, provider failures, session expiry, and administrator recovery are tested. This adds SSO convenience after local roles/sessions are established.

### APP-01 — Validated desktop URL handlers and editor launchers

Continue [issue #57](https://github.com/wispsy/pretty-notebook/issues/57). Define one canonical URI format carrying a notebook identity and validated note/action. Support allowlisted editor/terminal adapters; do not treat Ghostty or another terminal as a note editor by default.

**Accept:** URL parsing rejects hostile encodings, path escapes, unknown actions, and shell interpolation. AppleScript/`.app` registration, installation, permissions, updates, and removal are documented and tested. Launching a link never saves, publishes, or executes arbitrary code without the defined explicit workflow.

### PERF-01 — Optimize measured parsing and I/O bottlenecks

Measure notebook load, graph/search, rendering, image hashing, and remote publish first. Add cache invalidation keyed by current-content hashes and configuration; use bounded parallel reads/uploads only where the operation supports them.

**Accept:** benchmark gains are recorded on representative notebooks; concurrency preserves deterministic results, failure handling, source-change detection, and the stop-before-prune gate. No async API rewrite or new I/O dependency is required solely for style.

## 9. Source-idea coverage

Repeated planning notes are consolidated here so no major idea disappears.

| Planning idea | Resolution / cards |
| --- | --- |
| Local Markdown handling, Bold/Italic/etc. models, remove Python-Markdown | MD-01 builders; MD-02–MD-05 parser and measured removal gate |
| Mermaid local installation, CDN fallback, only when needed | STC-02 + STC-01 |
| Handwritten HTML/CSS and non-framework icons | STC-03 + STC-04 |
| Remote environment setup, app factory, container deployment | Existing factory retained; OPS-02 + OPS-03 |
| Contact form, database messages, management views | Storage already exists; WEB-07 + INT-01 |
| Comments, storage/views, related notifications | WEB-08 + INT-01 |
| Session tracking and retrieval | WEB-07 authentication sessions; OBS-01 optional aggregate analytics |
| SSO | AUTH-03 after local roles/sessions |
| Document temporary md_out and save requirements; live properties | CORE-03; current-content cache behavior in CORE-03/PERF-01 |
| Backlinks after rename, relationship UUIDs | ID-01 + LINK-02 |
| Better inline code, fenced-code copy/language controls | CODE-02 |
| Notebook/directory pages, next/related notes | NAV-01 |
| Sphinx/Read the Docs/wispsy.com documentation | DOC-02 |
| pydantic-settings | CFG-02 decision; optional web-layer evaluation |
| pnano, URL schemes, AppleScript/.app, editor/terminal options | APP-01; keep existing issue #57 |
| Front-end login, named users/groups, restricted links | AUTH-02, WEB-07, ACL-01, SHARE-01; tags do not authorize |
| In-browser editor | SRC-01 + SYNC-01 before EDIT-01 |
| Hash comparisons and two-way local/remote sync | PUB-05 one-way publishing; SRC-01 + SYNC-01 for authoritative Markdown |
| Multiple notebook paths, prefix/numbered slugs, authors | CFG-02 local profiles; PUB-04 explicit notebook slugs; AUTH-02/SRC-01 author identity |
| Back button, nb traversal history, back/forward | NAV-01, explicit opt-in history |
| Search via nb.find(), title/content toggles and search template | SEARCH-01; retain local regex compatibility |
| Favicon route and documented POST | WEB-06 |
| Replace Highlight.js, Rich, Click; zero-dependency goal | Optional future decisions driven by evidence; keep useful dependencies now. STC/CODE work does not require replacements. |
| Add Notes, command registration, notebook constructor cleanup | Existing generate_note retained; CORE-03 + CFG-02 |
| commands/test | OPS-03 runtime diagnostics; retain repository test suite |
| Hidden .pnbp settings/env/metadata/Git | CFG-02 + ID-01; private credentials separate; keep Git at notebook root |
| pretty-notebook distribution, pretty_notebook import, pnbp/nb aliases, web extra | Keep current names in 0.10; PACK-01 evaluates an actual packaged web surface and aliases |
| nb --prompt, pprint/pcat and programmable tool use | Keep pnbp pprint; explicit note show/edit in CORE-03. Evaluate a prompt UI separately only after command semantics stabilize. |
| Nested note files mapping to hierarchical paths, real 404 | ROUTE-01; existing recursion alone does not provide hierarchical publication |
| Concurrency for I/O/property retrieval | PERF-01 after profiling; bounded work and cache correctness |

## 10. Implementation references

Repository observations are pinned to the baseline above:

- [0.9.0 release](https://github.com/wispsy/pretty-notebook/releases/tag/v0.9.0) and [successful main CI](https://github.com/wispsy/pretty-notebook/actions/runs/36949289081).
- [Package metadata](https://github.com/wispsy/pretty-notebook/blob/681c41082e83e2df50a327024547ec64cd6f4f83/pyproject.toml).
- [Notebook loading/rendering/publication](https://github.com/wispsy/pretty-notebook/blob/681c41082e83e2df50a327024547ec64cd6f4f83/src/pnbp/models/notebook.py), [Note edit/save state](https://github.com/wispsy/pretty-notebook/blob/681c41082e83e2df50a327024547ec64cd6f4f83/src/pnbp/models/note.py), and [current flat link slugs](https://github.com/wispsy/pretty-notebook/blob/681c41082e83e2df50a327024547ec64cd6f4f83/src/pnbp/models/components/link.py).
- [Web deployment contract](https://github.com/wispsy/pretty-notebook/blob/681c41082e83e2df50a327024547ec64cd6f4f83/docs/web.md), [app factory](https://github.com/wispsy/pretty-notebook/blob/681c41082e83e2df50a327024547ec64cd6f4f83/apps/web/main.py), and [asset-loading template](https://github.com/wispsy/pretty-notebook/blob/681c41082e83e2df50a327024547ec64cd6f4f83/apps/web/templates/shared/layout.html).
- Source brief: **Pretty-Notebook 0.10 Planning**, current contents read 2026-10-05, version 157.

Primary technical references for implementation decisions:

- [HTTP conditional requests, RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-if-match): strong revision checking for state-changing requests.
- [CommonMark specification](https://spec.commonmark.org/0.31.2/) and [spec test tools](https://github.com/commonmark/commonmark-spec): parser cases and a deliberate supported dialect.
- [Distribution versus import packages](https://packaging.python.org/en/latest/discussions/distribution-package-vs-import-package/) and [name normalization](https://packaging.python.org/en/latest/specifications/name-normalization/): installation/import names need not match; punctuation variants do not create independent distribution names.
