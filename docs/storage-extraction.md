# Web storage extraction inventory

This inventory is based on `32c0bda` and preserves the supported one-host Linux
profile: up to four Gunicorn workers, one local SQLite database, one persistent
state root and one application version at a time. It defines the first consumer
for [PN-STORAGE-02](https://github.com/outside-labs/pretty-notebook/issues/187),
not an ORM replacement or a database-format change.

## Current ownership and coupling

| Source | Current responsibility | Reusable boundary |
| --- | --- | --- |
| [main.py](../apps/web/main.py), `create_app` lifespan | `RegisterTortoise` owns startup/close; schemas are not auto-generated; migration and catalog bootstrap complete before serving | Lifecycle sequencing can consume a storage facility, but the application owns readiness, resource construction and failed-startup cleanup |
| [schema.py](../apps/web/api/schema.py), `migrate` | Obtains Tortoise's default `SqliteClient`; validates history; uses `in_transaction`; temporarily disables foreign keys for the pre-v4 rebuild and restores enforcement | Ordered history, backup-before-upgrade and transaction/error rules are reusable; the SQL, validation callbacks and existing history table remain consumer-owned |
| [schema.py](../apps/web/api/schema.py), `_backup` | Own read-only stdlib SQLite source and destination connections in one `asyncio.to_thread` call; SQLite backup includes committed WAL; integrity check, file/directory sync, SHA-256 receipt and incomplete-file cleanup | First narrow consumer: an explicit consistent private SQLite snapshot facility |
| [process_lock.py](../apps/web/api/process_lock.py), `ProcessLock` | Task serialization plus nonblocking POSIX `flock`, cancellable polling, descriptor cleanup and OS release on process exit | Startup coordination pattern is reusable; lock path and application-wide writer policy remain local |
| [catalog.py](../apps/web/api/catalog.py), `PublicationStore` | Raw parameterized SQL through Tortoise; immutable blobs precede revision/head commit; checked writes revalidate inside a transaction | Connection/transaction facilities may eventually move; notebook identity, routes, aliases, hashes, ETags, tombstones and blob ordering stay here |
| [auth_api.py](../apps/web/api/auth_api.py), [forms.py](../apps/web/api/forms.py), [permissions.py](../apps/web/api/permissions.py), [notebooks.py](../apps/web/api/notebooks.py), [operation_logs.py](../apps/web/api/operation_logs.py) | ORM models and application SQL; token revocation, roles, hashed credentials, notebook ownership, scoped receipts | No extraction of authorization, identity or retention policy into a generic store |
| [atomic_io.py](../apps/web/api/atomic_io.py), layout/site APIs | Atomic complete settings/assets replacement; private create-if-absent defaults; shared writer lock | Filesystem publication policy remains here; a SQL transaction cannot roll back already-written files |
| [public_index.py](../apps/web/api/public_index.py), `PublicIndex.snapshot` | Re-queries committed public rows and computes revision/blob fingerprints before reusing process-local documents | Database remains authoritative; preserve refresh across workers, rather than promise shared in-memory caches |
| [backups.py](../src/pretty_notebook/_internal/backups.py), [web_state.py](../src/pretty_notebook/_internal/web_state.py) | Stopped-site snapshots/restores, service-stop evidence, lock, consistent database copy, whole-tree inventory, receipts and code/schema compatibility validation | Database snapshot primitive can be shared later; whole-site recovery policy and application integrity checks stay local |

Tortoise connections are asynchronous and owned by its backend. A future
Backpack Store connection cannot be substituted into `in_transaction`, used on
an arbitrary thread or treated as the same transaction. A generic snapshot owns
both of its stdlib connections within its own worker call. Migration ownership
must be explicitly designed before replacing any Tortoise transaction.

## Data and ordering that must survive

The existing `pnbp_schema_migrations` table keeps contiguous versions, exact
names, UTC application times and backup path/SHA-256 receipts. Its five names
are `base-schema`, `publication-catalog`, `scoped-permissions`,
`notebook-ownership` and `operation-logs`. Consumer-owned definitions in
[web_state.py](../src/pretty_notebook/_internal/web_state.py) also drive recovery
validation; do not create a second authoritative schema inventory in a library.
Unknown future versions, gaps, renamed steps and malformed current tables stop
startup without rewriting history. Fresh/current databases avoid extra backups.

Preserve account IDs, password hashes, token revocation UUIDs, inbox JSON and
timestamps, SQLite sequences, notebook/note UUIDs, grants and credentials,
publication routes/revisions/provenance and operation receipts. This inventory
does not translate existing rows into Backpack typed JSON records.

Before an applicable migration, write and validate a private consistent backup;
on backup failure make no schema changes. Apply all pending steps and history
rows in one SQL transaction. On migration failure roll back and retain the
usable backup. The v4 table rebuild must retain its pre-BEGIN foreign-key
procedure and validate references before commit.

For publication, a complete synced content-addressed blob is written first;
the revision and selected head commit together. A failed SQL write retains the
previous head and may leave a complete collectable orphan. Missing/corrupt
selected blobs fail closed. Legacy files, deleted and historical records must
not reappear or be collected accidentally. Migration database snapshots are
not full-site backups: recovery also needs pages, blobs, images, settings,
private environment and matching code.

`site.lock` serializes migration/bootstrap and application writers. Never unlink
or replace it while workers run. OS-exit release and cancelled-waiter descriptor
cleanup are required. More workers do not add concurrent SQLite writers. No
multi-host or network-filesystem guarantee follows from this extraction.

## First consumer and rollback

PN-STORAGE-02 should first replace only `schema._backup` internals with the
qualified Backpack Store snapshot interface from BP-MIG-01. Keep the current
async call boundary, `migration-backups` location, private modes, filename
prefix, return shape `(path, sha256)`, history receipts and all schema callbacks.
No automatic file migration or schema namespace rewrite is needed for this slice.
Keep the shared lock held for the existing backup/migration sequence.

Before adoption, qualify an immutable Backpack Store revision (or published
version), optional dependency/Python compatibility, snapshot destination policy,
connection cleanup, cancellation and failure mapping. Pretty Notebook's Python
3.11 profile must remain supported. BP-MIG-01 owns the reusable migration and
backup interfaces; BP-CONC-01 owns independent-process SQLite qualification.
Do not choose a new runtime dependency merely by writing this inventory.

Since this first slice changes no stored format, rollback is a code/dependency
rollback with the same complete version-matched stopped-site backup retained.
For any actual schema upgrade, restore the complete pre-upgrade state and its
matching application version. Never run old code against newer schema history
or mix database and blob trees from different checkpoints.

## Adopted snapshot consumer

The web migration backup now delegates to `backpack_store.snapshot_sqlite` at
qualified development revision `696936ea2af46876bee61aefbf703a52edecc529`.
The source archive and build tool have separate hash-locked requirements in
`apps/web/requirements-storage.lock` and `requirements-storage-build.lock`.
Install the build tool first, then the source with `--no-build-isolation`.
The published Backpack Store 0.1.0 alone does not provide this snapshot API.

Only the snapshot primitive moves. The async worker boundary, database filename
prefix, private destination, backup receipts, schema version 5, Tortoise
transactions, migration history, authorization and immutable blob ordering
retain their existing ownership. Snapshot failures stop startup before SQL
changes and return a value-free application error. Cancellation of the awaiting
task does not stop the already-running SQLite worker; this retains the existing
startup cancellation boundary and does not authorize migration retry in parallel.

This change introduces no data/schema translation. Both the prior application
and this checkout understand schema 5. Roll back code plus its dependency
environment with services stopped; retain the complete version-matched
database/blob/settings/environment checkpoint described in [backups](backups.md).
For an actual later schema upgrade, restore the full pre-upgrade checkpoint and
matching code before starting an older version.

## Acceptance to retain and port

The following existing tests are the extraction checklist. Keep application
assertions here; port the reusable mechanics to BP-MIG-01/BP-CONC-01 as their
interfaces land. Test names are exact and can be selected with `pytest -k`.

| File under `apps/web/tests/` | Tests / preserved behavior |
| --- | --- |
| `test_schema.py` | `test_legacy_upgrade_preserves_state_tokens_messages_and_backup`: legacy rows, authentication/revocation, receipts, permissions and restart without another backup |
| `test_schema.py` | `test_fresh_database_records_version_without_unnecessary_backup`, `test_failed_schema_changes_roll_back_and_leave_backup`, `test_backup_failure_prevents_schema_changes` |
| `test_schema.py` | `test_unknown_or_inconsistent_history_refuses_startup`, `test_incomplete_current_history_is_not_accepted`, `test_incompatible_legacy_schema_is_backed_up_and_not_replaced` |
| `test_schema.py` | `test_backup_includes_committed_wal_rows`, `test_migration_backup_symlink_is_refused`, `test_partial_backup_failure_removes_incomplete_file`, `test_non_sqlite_profile_requires_a_support_decision` |
| `test_failure_paths.py` | `test_tampered_migration_name_stops_startup_without_rewriting_state`, `test_worker_lock_rejects_a_nonregular_coordination_file` |
| `test_process_lock.py` | `test_independent_coordinators_serialize_and_cancellation_releases_waiter`, `test_failed_lock_open_releases_local_task_lock` |
| `test_atomic_io.py` | `test_first_settings_publish_is_complete_and_private`, `test_competing_initialization_preserves_the_winner_and_its_mode`, plus existing failed replacement/partial-write/mode checks |
| `test_catalog.py` | `test_failed_revision_transaction_keeps_head_and_produces_collectable_orphan`, `test_restart_after_blob_before_catalog_commit_keeps_previous_head`, `test_legacy_import_is_transactional_and_retry_preserves_originals`, `test_legacy_tombstone_survives_restart_without_resurrecting_original`, corruption/symlink and retained-history cases |
| `test_worker_deployment.py` | `test_four_workers_coordinate_startup_claims_and_checked_writes` (fresh and legacy): four real workers, one owner, one accepted stale-write competitor, visibility through every worker, one applicable backup, and restart |
| `test_backup_recovery.py` | `test_verified_restore_retains_all_persistent_behavior`: full application recovery rather than only successful SQLite integrity |

Also retain `tests/test_backups.py`, especially
`test_committed_wal_is_included_in_consistent_database_snapshot`,
`test_changed_sources_leave_unusable_checkpoint_and_original_intact`,
`test_active_source_lock_refuses_backup` and
`test_interrupted_restoration_never_marks_output_ready`.

No additional application acceptance is needed for this read-only inventory.
New backend ownership/cancellation tests belong to BP-ASYNC-01; simultaneous
migration/process exit tests belong to BP-CONC-01. At consumer adoption, run the
selected schema/failure/catalog/backup suites and the real four-worker test on
Linux, then retain the existing complete web CI coverage on Python 3.11/3.14.
The existing [server-state](server-state.md) and [backup](backups.md) guarantees
remain the acceptance contract.
