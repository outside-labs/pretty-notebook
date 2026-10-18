# Pretty Notebook web publisher

> [!IMPORTANT]
> `apps/web` is supported for public deployment only in the constrained
> topology described here. A deployment outside this profile has not passed
> the documented 0.11 checks. The released 0.9 contract remains
> a single-worker deployment.

The FastAPI application publishes HTML and images produced by `pnbp`, serves a
small public site, and stores contact-form messages in a local inbox. The web
application is deployed from the repository; it is not included in the `pnbp`
wheel.

## Supported deployment profile

| Area | Supported contract |
| --- | --- |
| Platform | Linux x86_64 with CPython 3.11 or 3.14 and the hash-locked wheel set |
| Application | One Gunicorn instance with 1–4 `uvicorn_worker.UvicornWorker` processes; four by default |
| State | One local persistent data directory containing one SQLite database, pages, images, and layout settings |
| Publication ownership | Explicit notebook owners with isolated namespaces, inventories and pruning |
| Editors | Explicit site-owner, editor, reader and inbox roles; notebook publishing requires a grant and trusted authors |
| Network | The application binds to loopback behind a TLS-terminating reverse proxy |
| Operations | One host, stopped-site backups, and version-matched restores |

Multiple application instances, shared or network filesystems,
remote databases, untrusted editors, and independent notebooks sharing a page
namespace are not supported. The macOS URL handlers are also outside this
support decision.

Published page HTML, `NAV_BRAND`, and `FOOTER` are intentionally rendered as
trusted owner-authored HTML. They are not safe contribution surfaces for
untrusted users. Published page content is stored as data and is never compiled
as a server-side Jinja template.

Use [VPS deployment commands](vps-deployment.md) to generate systemd/nginx setup
and stopped-service upgrade bundles, or the optional [Linux container profile](container-deployment.md). The manual contract below remains available.

## Install a reviewed checkout

Use a dedicated service account and an explicitly reviewed 0.11
commit. Set `PNBP_REVISION` to that full commit SHA. The released `v0.9.0`
tag retains its historical single-worker contract.

```bash
git clone https://github.com/outside-labs/pretty-notebook.git pnbp
cd pnbp
: "${PNBP_REVISION:?Set a reviewed 0.11 commit SHA}"
git checkout --detach "$PNBP_REVISION"

python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  --require-hashes \
  --only-binary=:all: \
  --requirement apps/web/requirements.lock
.venv/bin/python -m pip install --editable . --no-deps
.venv/bin/python -m pip check
```

The lock is verified for Linux x86_64 on CPython 3.11 and 3.14. Other
platforms are not part of the supported public-deployment profile.

For dependency updates, regenerate from the repository root and confirm that
both Python targets produce the same file:

```bash
uv pip compile apps/web/requirements.txt --generate-hashes \
  --python-version 3.11 --python-platform x86_64-unknown-linux-gnu \
  --no-annotate --no-header --output-file apps/web/requirements.lock

uv pip compile apps/web/requirements.txt --generate-hashes \
  --python-version 3.14 --python-platform x86_64-unknown-linux-gnu \
  --no-annotate --no-header --output-file /tmp/requirements-3.14.lock

cmp apps/web/requirements.lock /tmp/requirements-3.14.lock
```

## Configure secrets and persistent state

Create a private persistent directory outside the checkout. Keep the database
inside it so one stopped-site backup contains all server state.

```bash
install -d -m 0700 /srv/pnbp-web
umask 077
python -c 'import secrets; print(secrets.token_urlsafe(32))'
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Put the two different generated values in an untracked `apps/web/.env` file:

```bash
PNBP_DATA_DIR=/srv/pnbp-web
PNBP_ALLOWED_HOSTS=notes.example.com
PNBP_DATABASE_URL=sqlite:///srv/pnbp-web/db.sqlite3
JWT_SECRET=PASTE_FIRST_GENERATED_VALUE_HERE
JWT_ALGO=HS256
PNBP_BOOTSTRAP_TOKEN=PASTE_SECOND_GENERATED_VALUE_HERE
```

`JWT_SECRET` and `PNBP_BOOTSTRAP_TOKEN` must each contain at least 32 UTF-8
bytes. `PNBP_ALLOWED_HOSTS` is a comma-separated list of exact hostnames; a
wildcard is rejected. Protect the environment file with mode `0600`. Never
commit it.

The bootstrap token is temporary. It authorizes only the initial owner claim
and should be removed after that claim succeeds. `JWT_SECRET` is durable state:
changing it invalidates every bearer token.

## Start the supported process

Run from `apps/web` with a restrictive umask:

```bash
cd apps/web
umask 077
exec ../../.venv/bin/gunicorn main:api --no-control-socket \
  --workers 4 \
  --worker-class uvicorn_worker.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --access-logfile -
```

Do not expose port 8000 directly. Configure the reverse proxy to:

- terminate TLS, redirect HTTP to HTTPS, and set HSTS;
- preserve a `Host` value listed in `PNBP_ALLOWED_HOSTS`;
- connect only to the loopback listener and trust forwarded headers only from
  that proxy;
- allow slightly more than 10 MiB of request body for multipart image
  overhead, while rejecting larger requests before they reach the app;
- rate-limit `/api/token`, `/api/users`, authenticated write routes, and
  `/forms/contact`;
- apply finite connection, header, and request timeouts; and
- avoid logging authorization headers, passwords, tokens, or form bodies.

Monitor `GET /healthz` over the loopback listener. It checks SQLite and the
validated layout file and returns `503` when either is unavailable. It does not
test free disk space, a writable filesystem, or external CDNs.

The default layout uses local project-owned CSS and SVGs. Select
`PNBP_ASSET_MODE=local` for reviewed local Mermaid and Highlight.js assets with
validated checksums and integrity metadata; no browser CDN is needed in this
profile. See [browser assets](assets.md) for explicitly selected CDN fallbacks
and [appearance](appearance.md) for palettes and persistent overrides.

## Claim the initial owner

Configure a notebook client's `API_BASE` with the public HTTPS URL and leave
`API_TOKEN` empty. Then create the initial owner:

```py
import pnbp

nb = pnbp.Notebook()
nb.create_api_user(username="alice")  # asks for password and bootstrap token
nb.refresh_token()                    # asks for username and password
nb.get_authed_user()
```

Passwords must contain at least 12 characters and no more than 72 UTF-8 bytes.
After the owner is created:

1. Remove `PNBP_BOOTSTRAP_TOKEN` from the server environment.
2. Restart the Gunicorn service and its workers.
3. Confirm `/healthz` and `nb.get_authed_user()`.

Anonymous registration never reopens, even if the owner row is deleted.
Recover the owner database from backup instead. Later accounts can be created
only while authenticated as user ID 1. All accounts can publish arbitrary HTML,
upload images, change layout settings, and read the local inbox, so create
accounts only for equally trusted site editors.

Tokens last 30 days. Issuing a new token or resetting a password revokes that
account's previous token. The client stores refreshed tokens in a
separate private `.pnbp/secrets.json`; portable settings contain no credentials.
Legacy `pnbp_settings.json` tokens remain readable. Follow
[credential storage](settings.md#credentials-and-sharing), exclude credentials
from shared backups, and treat every bearer token as a password.

## Publish a selected notebook

Review changes before sending them:

```bash
pnbp commit-stage --json --mode checked
pnbp commit-remote --mode checked
```

The client compares source/rendered/image hashes and checked
remote revisions. Preview writes no local receipts or remote content, and a
conflict requires a fresh reviewed plan. See [checked publishing](checked-publishing.md)
for preconditions, retries and legacy fallback. The published 0.9.0 client uses
timestamp comparisons; `touch-all-public` requests a refresh in that legacy mode.
`--refresh-images` explicitly resends referenced images.

Pruning is intentionally explicit. Use `--prune` only after reviewing
`pnbp commit-stage` and confirming the selected `SERVER_NOTEBOOK` scope. It deletes pages absent from
that notebook only. Requests without a notebook header select `default`;
legacy endpoints enforce the same ownership boundary. Shared multi-notebook
ownership remains outside the historical 0.9 contract.

The server accepts publication slugs made from lowercase letters, digits, and
single hyphens, with explicit hierarchical routes in development. It limits publication bodies to 2,000,000 characters. Image
uploads are limited to 10 MiB, must use PNG, JPEG, GIF, or WebP extensions, and
must match the corresponding file signature. SVG and arbitrary file uploads
are rejected.

A publication run is not a transaction across the whole site. Each individual
page, image, or layout replacement is atomic, and a failed upload stops the
client before pruning. Earlier successful uploads from that run remain in
place and can safely be retried.

## Site titles and favicon

The layout's `TITLE` is the site title. Set it in the notebook's presentation
settings and send it with `pnbp commit-settings` or authenticated
`POST /api/layout`. The home page uses that title; publication pages use
their configured publication title followed by the site title. Contact and
missing-page responses have their own page titles. Titles are escaped as text.

The client includes a dedicated favicon command:

```bash
pnbp favicon ./site.png
# For the local development server:
pnbp favicon ./site.png --local
```

From Python, use `nb.post_favicon("./site.png")`. Both use the notebook's
`API_BASE` and bearer token. The server requires the site-owner role and a `site` credential scope for
site-wide favicon changes. Notebook editor grants do not grant site management.

The request is `POST /api/favicon` with a multipart field named `file`, a
`.png` filename and the owner's `Authorization: Bearer ...` header. A successful
request returns `201` with `url`, `width`, and `height`. Static PNG files are
limited to 1 MiB and 512 pixels per side; chunk checksums, pixel-data lengths and
PNG encoding are validated. Animated PNG, ICO, SVG, corrupt or truncated images
are rejected with `400`; files exceeding 1 MiB return `413`. Invalid or absent
tokens return `401`, and other accounts return `403`.

The validated file is atomically stored as `PNBP_DATA_DIR/favicon.png` and
survives restarts and stopped-site backups. Every rendered page links to
`/static/favicon/<sha256>.png`, including a configured URL prefix. That route
serves `image/png` with an immutable cache policy. Replacement changes the URL;
a newly loaded page therefore requests the replacement without reusing a stale
cache entry. Old version URLs return `404` from the server. `/favicon.ico`
redirects to the current PNG with `307` and `Cache-Control: no-store`.
Without an uploaded favicon, no icon link is emitted and favicon requests
return `404`. A failed write preserves the previous icon.

## Public routes and local inbox

The home page, published single-slug pages, images, theme switch, contact page,
and contact submission endpoint are public. Management APIs and the inbox read
endpoint require bearer authentication.

`POST /forms/contact` validates the email address and a message of at most 5,000
characters, then stores it in the SQLite `formsubmission` table. It does not
send email. Retrieve entries with an authenticated request to
`GET /api/forms/contact/submissions`; `limit` accepts 1–100 and `offset`
supports pagination.

Contact messages are personal data. Limit retention, restrict filesystem and
backup access, and rate-limit the public form at the reverse proxy.

## Persistent data and migration

The 0.10 application applies [versioned SQLite migrations](server-state.md)
before serving requests. Existing databases receive a private pre-migration
snapshot; upgrades preserve account and token state rather than regenerating it.

The data directory contains:

| Path | Contents |
| --- | --- |
| `db.sqlite3` | Accounts, token state, contact submissions, migrations, and publication revisions |
| `pages/*.html` | Retained legacy page originals |
| `pages/.blobs/*.html` | Immutable catalog-selected bodies and referenced history |
| `migration-backups/*.sqlite3` | Private pre-migration database snapshots |
| `images/*` | Validated published images |
| `favicon.png` | Validated owner-managed site favicon, when configured |
| `web-settings.json` | Navigation, title, theme, and owner-authored layout HTML |

New directories are created with mode `0700`, and a newly seeded settings file
uses mode `0600`. The service account must be the only writer. Existing paths
keep their current permissions, so verify them during every deployment.

Older checkouts stored state at `apps/web/db.sqlite3`,
`apps/web/templates/pages`, `apps/web/static/imgs`, and
`apps/web/web-settings.json`. Before the first 0.9 start, stop the old process
and copy those contents into the corresponding paths under `PNBP_DATA_DIR`.
Keep the originals until the new site, authentication, inbox, and published
assets have been verified. Legacy wrapped page files are read as plain page
bodies without evaluating their embedded Jinja syntax.
The 0.10 catalog imports these originals and selects immutable revisions for
new uploads; do not edit a retained flat file to change an existing catalog head.

## Backup, restore, and recovery

The preview-first [verified backup and restore commands](backups.md) automate
the current stopped-site SQLite/files/environment contract into new locations.
The manual recovery procedure below remains available.

Use stopped-site backups. Copying a live SQLite database and files separately
does not provide a supported point-in-time snapshot.

```bash
systemctl stop pnbp-web
install -d -m 0700 /srv/backups/pnbp-web-YYYYMMDD-HHMMSS
cp -a /srv/pnbp-web/. /srv/backups/pnbp-web-YYYYMMDD-HHMMSS/
systemctl start pnbp-web
curl --fail --header 'Host: notes.example.com' http://127.0.0.1:8000/healthz
```

Store the backup encrypted and separately from the host. Retain the deployed
commit identifier and the `JWT_SECRET` in the same protected recovery record.
The temporary bootstrap token is not needed for restore.

To restore, stop the service, preserve the failed data directory under a new
name, copy one complete backup into a newly created private data directory,
restore ownership and mode, deploy the matching application version and
`JWT_SECRET`, then start the service. Verify:

- `/healthz` and the public home page;
- a representative published page and image;
- owner authentication and an authenticated API request; and
- contact inbox pagination.

If an update fails, stop the process and restore both the version-matched code
and the complete stopped-site backup. Do not combine a database from one backup
with pages or settings from another.

## Failure behavior

- Page, image, and layout writes use a temporary sibling file followed by an
  atomic replacement. A failed replacement leaves the old file intact.
- SQLite commits each successful account or form operation before success is
  returned.
- Invalid or missing bearer tokens return `401`; the temporary bootstrap secret
  cannot turn an invalid bearer token into an anonymous request.
- Corrupt layout state or an unavailable database makes `/healthz` return
  `503` without exposing an internal error.
- Unsupported hosts return `400` before application routing.

## Development verification

The integration suite requires a full checkout:

```bash
cd apps/web
python -m pip install --editable ../..
python -m pip install --requirement requirements-test.txt
python -m coverage run --source=api,views,main -m pytest tests
python -m coverage report --show-missing --fail-under=90
```

CI runs the suite and the exact four-worker Gunicorn command on Python 3.11 and
3.14. It also checks that an allowed host reaches `/healthz` and an unlisted
host is rejected.

## Explicit support decision

The 0.9 safety gate approves public deployment only for the supported profile
at the top of this document. The tests cover authentication and owner bootstrap,
token revocation, secrets validation, public routes, bounded uploads, local
inbox persistence, atomic filesystem updates, SQLite restart persistence,
stopped-site backup and restore, health failures, host filtering, and the
production process command.

The gate does not approve horizontal scaling, multiple workers, shared
multi-notebook pruning, untrusted editors, automated email delivery, or the
macOS URL handlers.

## Browser asset deployment

See [browser assets](assets.md) for the reviewed manifest, local/CDN policy,
integrity checks, supported Highlight themes, and deployment verification.
The default selects local assets first; strict local mode requires no runtime
script, style, or font requests to external services.

See the [web coverage audit](web-coverage.md) for measured statement/branch
coverage, residual paths, and the distinction between coverage and support.

## Roles and script credentials

Site owners manage accounts, layout, identity and the inbox. Editors receive
explicit `read`, `publish` and `logs` grants for individual notebooks. Readers
start without grants. Inbox operators have inbox access without publication or
site administration. New accounts start as readers; owners assign roles with
`PUT /api/users/{id}/role` and replace notebook grants with
`PUT /api/users/{id}/grants` (`notebook`, `permissions`). Removing a grant takes
effect on the next request. At least one site owner must remain.

Upgrading existing state assigns the original account the owner role and other
existing accounts editor grants for the `default` notebook. Existing credentials
retain their revocation state. Review those legacy grants before sharing a site.

`POST /api/credentials` accepts `scopes`, `notebook` (default `default`) and
`lifetime_days` (1–90). It returns a script token once; only its hash is stored.
Scripts cannot exceed their account's current role/grants. List credential IDs
with `GET /api/credentials` and revoke with `DELETE /api/credentials/{id}`.
Password changes and replacement account tokens invalidate existing scripts.
Use `X-PNBP-Notebook` to select a notebook; absent headers select `default`.

## Independent notebooks

Create an editor account, then let a site owner create its notebook with
`POST /api/notebooks` and `{"slug":"field-notes","owner_id":2}`. The owner
record and that editor's read/publish/log grants commit together. Notebook
slugs are permanent namespace identifiers. Existing routes occupying a proposed
namespace must be migrated before it can be claimed. `GET /api/notebooks`
returns only the requesting account's granted notebooks, or all notebooks for
site owners.

For the local notebook, set `SERVER_NOTEBOOK` and `NOTEBOOK_SLUG` to
`field-notes`, and `ROUTE_MODE` to `namespaced`. Publications use
`/n/field-notes/<note-path>`, with no site-wide flat aliases. The client sends
`X-PNBP-Notebook: field-notes`; images use
`/static/imgs/n/field-notes/<filename>`. Two notebooks can use the same note
and image names. Layout, favicon, appearance and inbox remain site-wide owner
operations. Notebook ownership does not grant site administration.

Requests without a notebook header address `default`, including legacy
inventory and deletion endpoints. Existing flat/hierarchical routes and
previous single-notebook namespaced routes remain there after upgrade. No
unscoped pruning operation can delete another notebook's publications. Every
selected notebook is still a single-notebook checked-publishing scope; the
capabilities response additionally advertises `independent_notebooks`.

All content and attachments in this profile are public. Private-reader and
browser-session support require their separate permission/rendering gates.

## Durable operation logs

`GET /api/logs?limit=100&before=0` returns the selected notebook's newest
publication, image and pruning operation receipts. It requires a `logs` grant
and accepts at most 100 rows; pass the oldest returned `id` as `before` to read
older rows. Script credentials can grant `logs` without publication access.

Receipts contain an event ID, operation correlation UUID, account ID, operation
type, outcome, HTTP status and UTC timestamps. They contain no note paths,
titles, Markdown, HTML, image filenames, request bodies, credential values or
exception messages. Responses include `X-PNBP-Operation-ID`; clients can supply
a UUID in that header to correlate multiple requests or retries. A correlation
ID is diagnostic metadata and does not make writes idempotent; checked
publication ETags still govern retries.

A start receipt is committed before a publication attempt. A logging-start
failure returns 503 before publication. A completion-receipt failure preserves
the actual publication response and the existing `started` receipt; it cannot
turn an already committed publication into a reported failed save. A process
interruption also leaves `started`, which means completion is unknown and
requires checking the current inventory. Successful and failed outcomes are
retained across restart. Each subsequent operation removes receipts older than
30 days and bounds each notebook to 10,000 rows, including interrupted receipts.
No webhook delivery is enabled.

The CLI's `pnbp logs` reads local receipts; `pnbp logs --remote` reads the
selected server notebook. Both accept `--limit` (1–100) and `--before`. Local
collect commands, `Notebook.save_all_notes()` flushes and actual publication
attempts record the same redacted lifecycle in the private
`.pnbp/operations.sqlite3` database. Dry-run publication, empty flushes and log
reads create no log state. Local logs follow the same retention/count limits;
local database access follows the notebook filesystem's ownership permissions.
The compatibility client is also available as `pnbp.commands.logs`.
