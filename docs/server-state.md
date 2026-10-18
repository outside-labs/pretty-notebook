# Versioned server state (0.10)

The supported web profile is one Gunicorn instance with up to four workers, one local
SQLite database, and one owning notebook. Starting the application now runs ordered schema migrations before
accepting requests. It no longer generates the current ORM schema on every
start. Migration version 1 establishes the supported account and contact inbox
tables and records the baseline in `pnbp_schema_migrations`.
Version 2 creates the publication catalog and its revision/head constraints.
Version 3 adds explicit roles, notebook grants and hashed script credentials,
while preserving account-token revocation state. The original owner remains
a site owner; existing other accounts receive editor grants on `default` only.

Existing 0.9 tables are retained. Account IDs, password hashes, token revocation
state, inbox payloads/timestamps, and SQLite sequence counters are preserved.
Missing supported tables are created; incompatible legacy columns stop startup
instead of rebuilding accounts. Unknown future versions or inconsistent history
also stop startup. Use a matching application version and verified backup.

Before upgrading an existing database, the application uses SQLite's backup API
to write a consistent private snapshot, including committed WAL data, under
`DATABASE_DIRECTORY/migration-backups/`. Each migration record includes its name,
UTC time, backup path, and SHA-256 receipt. The database backup uses owner-only
file permissions. Fresh empty databases and in-memory tests need no backup;
starting an already-current database creates no additional migration backup.

Migrations use one SQL transaction. A schema failure rolls back its changes and
leaves the backup available. A backup failure stops before schema changes. Keep
backup receipts and previous application versions locally; these files contain
account/token data and belong in private, encrypted backup storage.

## Recovery

Take a complete stopped-site backup before deploying an upgrade, following the
[supported backup instructions](web.md#backup-restore-and-recovery). Automatic migration
snapshots cover the database; they do not replace a complete backup of images,
settings, and page content.

If startup fails, stop the process and retain the current database, its SQLite
sidecars, and the recorded backup before changing files. A rolled-back migration
can be retried after repairing storage or configuration. Do not remove migration
history or regenerate account tables to get past an error.

To restore a pre-upgrade version, stop the application, preserve the failed state
separately, and restore one complete version-matched stopped-site backup into a
new private data directory. Configure that directory and run the corresponding
application version. Check `/healthz`, owner authentication, token state, inbox
messages, and public pages before returning the site to service. Never combine
unrelated databases, pages, or sidecars from different backups.

## Publication catalog

The catalog contains one default notebook UUID, distinct note UUIDs, canonical
flat routes, aliases, titles, public/deleted visibility, and a current revision.
Each revision records its exact rendered/body SHA-256, optional source hash,
optional renderer fingerprint, observed HTML features, and UTC publication time.
Legacy HTML cannot prove Markdown or renderer provenance: those fields remain
`NULL`. Catalog UUIDs are generated server identities; no content hash guesses
the identity of a local source notebook. Explicit client identity binding and
checked publication are the later PUB-05 protocol.

Startup imports supported flat `pages/*.html` files into the catalog while
retaining the original files and modification times. Known legacy template
envelopes are unwrapped as data, including their line-ending variants; embedded
Jinja syntax is never compiled. Identical page bodies can share one immutable
blob while keeping distinct note UUIDs. A failed import rolls back all new note
records, keeps originals, and can retry on the next start. Complete orphan blobs
may remain after that failure.

New bodies live in owner-only `pages/.blobs/SHA256.html` files. A body is fully
written and synced before SQLite selects its revision. The revision and head
commit in one transaction. A failed database write leaves the previous public
head usable; a missing or corrupt selected blob fails closed. Retain the whole
pages directory in stopped-site backups, including `.blobs` and legacy originals.

The `/api/publishment`, `/api/publishments`, and delete response shapes remain
compatible. Successful uploads now change the catalog instead of overwriting
flat page files. Inventory timestamps describe selected revisions. Deletion
removes the public head and listing while retaining historical revisions/blobs;
republishing that route continues its existing catalog identity and revision.
An uncataloged legacy file added externally remains readable as data until the
next startup imports it. Existing catalog heads take precedence over original
flat files, and deleted records prevent those originals from reappearing.

## Orphan maintenance

The process-local `app.state.publications.collect_orphans(dry_run=True, limit=200)`
method previews a bounded batch of complete blobs that no revision references.
Passing `dry_run=False` explicitly collects that batch. The collector shares
the publication write lock, checks payload hashes, and considers every revision,
including historical and deleted notes. It leaves unmanaged files and partial
temporary files alone. A truncated report can be repeated for subsequent batches.
No automatic history deletion or blob collection runs at startup.

Use a complete backup before deliberate maintenance. A failed upload's orphan
body can be removed only after the catalog proves it is unreferenced; existing
flat originals should be retained until migration and public pages are verified.
This catalog does not add independent notebook ownership or shared pruning.

## Worker coordination

Workers on the same Linux host share `site.lock` in the persistent settings
root. A task lock plus a POSIX file lock serializes migrations, legacy imports,
initial owner claims, checked publication writes/deletions, blob collection,
attachment writes/pruning and owner presentation writes. The OS releases a
process's lock when it exits; cancelled waiters close their descriptors.
Never delete or replace `site.lock` while workers are running.

SQLite and immutable blobs remain authoritative. Each worker refreshes public
search/navigation snapshots from committed revision signatures, so another
worker's publication is visible without restarting. There is one SQLite writer
at a time; more workers increase request concurrency, not write throughput.
This profile does not support network filesystems or multiple hosts.

The earlier single-worker limit reflected process-local locks and untested
concurrent migration/bootstrap paths. Four workers reading ordinary pages could
appear healthy while simultaneous writes or fresh startup still raced. The
0.10 tests now start four real Gunicorn workers on fresh and legacy databases,
race owner claims and stale writes, verify reads through every worker, and
restart the same state. Full-version upgrades still stop the service before
backing up and migrating; do not mix different application versions.

Fresh default settings are created from a private complete sibling file and
published with an atomic create-if-absent link. Concurrent startup preserves
the first winner and existing modes; no reader sees partly written defaults.
