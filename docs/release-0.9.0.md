# pnbp 0.9.0

`pnbp 0.9.0` is the first stable 0.9 release of the Pretty Notebook Python
library and command-line interface. It turns the release-candidate work on data
safety, deterministic lookup, rendering, publication, CLI behavior, and
configuration into the supported package release.

## Installation

Python 3.11 or newer is required.

```bash
python -m pip install --upgrade pip
python -m pip install pnbp==0.9.0
```

The web publisher is a repository application and is not included in the
`pnbp` wheel.

## Supported scope

| Surface | 0.9.0 status |
| --- | --- |
| `pnbp` Python library | Supported on Python 3.11 or newer |
| `pnbp` command-line interface | Supported on Python 3.11 or newer |
| `apps/web` publisher | Supported only in the documented single-worker, single-SQLite, single-notebook topology |
| Shared multi-notebook pruning | Not supported |
| `pnano.app` and `ppnbp.app` URL handlers | Experimental and unsupported |

## Package highlights

- Note edits have an explicit pending state; preview operations preserve it,
  reloads refuse to discard it silently, and saves use failure-safe replacement.
- Notebook lookup is exact-first and normalizes only terminal note extensions.
  Commands require explicit fuzzy acceptance before mutating an approximate
  target.
- Protected code and HTML remain literal while Markdown extensions process the
  surrounding note.
- Task settlement records completions before clearing source tasks.
- Collection dispatch is non-recursive, intended collection commands are
  restored, and cleanup revalidates destructive targets at execution time.
- Code extraction is contained to validated paths and preserves source bodies.
- Notebook Git automation verifies the repository boundary and refuses to mix
  unrelated staged changes into an automated notebook commit.

## Publication behavior

- One exact predicate selects public notes across staging, HTML output, and
  remote synchronization.
- Publication preflight validates every page and referenced image before the
  first remote side effect.
- Page and image failures stop synchronization before pruning; HTTP failures
  produce a nonzero CLI exit.
- Remote pages are preserved by default. `--prune` is explicit and is supported
  only when one notebook owns the complete remote namespace.
- Existing images are preserved by default; `--refresh-images` explicitly
  resends referenced images.
- `pnbp commit-settings` targets the configured remote service by default and
  uses localhost only with `--local`.

## Authentication and configuration

- `PNBP_SETTINGS=off` disables `pnbp_settings.json` loading even when the file
  exists.
- Generated settings include all required fields. On POSIX systems, generated
  settings and files updated with a refreshed bearer token are restricted to
  mode `0600`.
- Token responses are redacted from terminal output, and API calls use finite
  connection and read timeouts.
- Initial web-owner creation accepts a separate bootstrap token without sending
  an invalid `Bearer None` header.
- Refreshing a token no longer sends the previous bearer token to the login
  endpoint.

## Migration notes

- The supported executable is `pnbp` with subcommands. Older `nb-*` and `nbn-*`
  entry points are not the 0.9 interface.
- Review exact note names before mutation. Add `--fuzzy` only when an approximate
  target is intentional and the command offers that option.
- Review `pnbp commit-stage` before using `--prune`, and do not point independent
  notebooks at one destructive publication namespace.
- Treat `pnbp_settings.json` as a secret when it contains `API_TOKEN`; exclude
  it from version control and backups shared with others.
- A first owner on the supported web publisher requires the temporary bootstrap
  secret described in the [deployment guide](https://github.com/wispsy/pretty-notebook/blob/main/docs/web.md).

## Repository web publisher

The 0.9 web safety gate separately approved public deployment for one narrow
profile: Linux x86_64, Python 3.11 or 3.14, one Gunicorn worker, one local SQLite
database and persistent data root, one notebook owning the page namespace,
trusted editors, and a TLS reverse proxy.

That gate adds explicit host filtering, strong fixed JWT settings, a temporary
owner-bootstrap secret, persistent state configuration, bounded and
signature-checked image uploads, atomic file replacement, validated layout
inputs, health and security headers, restart persistence, stopped-site backup
and restore coverage, and a production-command smoke test. Owner-authored page
HTML is stored as data and is never compiled as a server-side Jinja template.

Read the complete [web deployment contract](https://github.com/wispsy/pretty-notebook/blob/main/docs/web.md)
before exposing the application publicly. Horizontal scaling, multiple workers,
remote databases, shared filesystems, untrusted editors, and independent
notebooks sharing a prune namespace remain unsupported.

## Security and dependency work

- The web dependency set is hash-locked and verified for Linux x86_64 on Python
  3.11 and 3.14.
- AnyIO, PyJWT, and urllib3 advisories identified during release preparation are
  resolved in the locked web environment.
- Authentication, bootstrap, token revocation, public routes, uploads, local
  inbox storage, persistence, backup/restore, and failure paths have focused
  integration coverage.

## Release verification

The published `0.9.0rc1` wheel passed the documented
[candidate-readiness exercise](https://github.com/wispsy/pretty-notebook/blob/main/docs/release-0.9.0-readiness.md)
on CPython 3.11.16 and 3.14.7, producing a GO decision for this final release.

The final release workflow requires the `v0.9.0` tag to match the package
version, compiles Python with warnings as errors, runs release-blocking Ruff
rules and the regression suite, builds the source and wheel distributions,
checks metadata strictly, and smoke-tests an installed wheel with `pip check`,
an import, CLI help, and a representative Notebook load. Publication uses the
protected `pypi` environment and PyPI trusted publishing.
