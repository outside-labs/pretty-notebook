# Pretty Notebook 0.11.0

The foundation release adds a typed Markdown engine, the expose-interface CLI,
operations tooling, scoped permissions, independent public notebook ownership,
and durable operation logs. Python 3.11 or newer remains supported.

## Install and upgrade

```sh
python -m pip install --upgrade pretty-notebook==0.11.0
```

`pretty_notebook` is the canonical import; `pnbp` imports and the executable
remain compatible. The final metadata-only `pnbp==0.11.0` package depends on
`pretty-notebook==0.11.0` exactly. Uninstall pre-0.10 `pnbp` before installing
the canonical package because those older wheels own overlapping files. See
[package migration](package-migration.md).

Back up notebook source and the complete stopped web deployment before an
upgrade. Server migrations advance to schema 5, preserve existing notebook
IDs/publication revisions and account-token revocations, and keep the legacy
namespace in `default`. The original account becomes a site owner; other
existing accounts receive editor grants on `default` only. Review those grants
before adding independent notebooks. Restore a version-matched complete backup
when rolling back; older application code cannot open schema 5.

## Included changes

- Typed source-aware Markdown parser, notebook extensions, shared headings and
  rendering metadata. Python-Markdown is available through the optional
  `legacy-markdown` extra. Read [renderer migration](markdown-migration.md) for
  intentional dialect changes and supported limits.
- Native expose-interface commands and invocation-local context. The core
  installation no longer requires Click; the separate web environment retains
  Uvicorn's Click dependency.
- Pinned Linux container planning, redacted diagnostics and preview-first
  stopped-site backup/restore with complete state/environment hash receipts.
- Explicit owner/editor/reader/inbox roles, notebook grants, hashed expiring
  script credentials and live revocation. New accounts start without notebook
  grants. Reader roles do not enable private content in this release.
- Independent public notebooks at `/n/<slug>/`, isolated image storage and
  ownership-scoped inventory/update/pruning, including legacy API endpoints.
  Set matching `SERVER_NOTEBOOK`/`NOTEBOOK_SLUG` and namespaced routes on clients.
- Durable redacted operation receipts, notebook-scoped `GET /api/logs` and
  `pnbp logs [--remote]`, bounded pagination and retention. Interrupted receipts
  preserve uncertainty; checked ETags and inventory still govern retries.

## Supported boundary

The FastAPI application remains a separate repository deployment, with pinned
requirements, one Gunicorn instance with 1–4 coordinated workers, one local
SQLite database/data root, a TLS reverse proxy and trusted editors. All
publications and attachments remain public, including across independent
notebooks. HTML authored by trusted editors retains the existing rendering
policy; this release enables no browser authentication cookies or untrusted
collaborative HTML authors. Read [web deployment](web.md).

Browser sessions/owner console, private readers/protected attachments, note
shares, authoritative remote Markdown/history, bidirectional sync and browser
editing remain deferred. Checked publication receipts are not bidirectional
source synchronization. Optional installed-wheel web packaging, webhooks,
external identity providers, distributed storage and macOS protocol handlers
also remain deferred. Hosted documentation and actual deployment are separate
operations; tagged GitHub documentation is the release reference.

The [readiness record](release-0.11.0-readiness.md) tracks distribution,
upgrade/recovery and final publication checks.
