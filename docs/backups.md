# Verified stopped-site backups

`pnbp deploy backup` and `pnbp deploy restore` preview by default. `--apply`
performs the operation after verifying that the managed systemd service or
matching container is stopped. The commands never stop, switch or start a live
service. Use the planned account or root where private state requires it.

A checkpoint contains the complete local SQLite/files/settings state, private
environment, deployment parameters, matching code revision/package version and
SHA256/size receipts. SQLite's backup API includes committed WAL data. Every
retained publication body and database reference is checked before a checkpoint
becomes usable. Recovery supports the current schema and exact recorded code;
use the matching checkout or local container image.

## Preview and create

Choose the same domain, revision and deployment options used for your
[VPS](vps-deployment.md) or [container](container-deployment.md). The checkpoint's
parent directory must already exist. Output must be a new location separate
from source state and the environment file.

```bash
pnbp deploy backup --domain notes.example.com --revision FULL_COMMIT_SHA \
  --output /var/backups/pretty-notebook/checkpoint-01
```

Review the report. For VPS application, independently stop the planned systemd
service before repeating with `--apply`. For containers, add `--profile container`
and use `docker compose stop`, retaining the stopped container so its image and
process state can be verified. A missing service/container is insufficient
stopped-state evidence.

```bash
pnbp deploy backup --domain notes.example.com --revision FULL_COMMIT_SHA \
  --output /var/backups/pretty-notebook/checkpoint-01 --apply
```

The VPS checkout must be clean and match the full SHA. Container recovery checks
the immutable image ID as well as its revision and package version. Both verify
the private environment and complete current schema. Backup holds the existing
site coordination lock, compares source inventories before/after copying and
rechecks stopped state and code identity before completing.

The checkpoint directory has mode 0700, files mode 0600. No secrets, account
records, inbox messages or publication bodies are printed. The private manifest
records filenames/hashes. Environment files are limited to 1 MiB and receipts
to 16 MiB. Keep the complete checkpoint together.

## Verify and restore elsewhere

Preview verifies the checkpoint, all recorded files, SQLite state and matching
code before proposing a new restore directory:

```bash
pnbp deploy restore --domain notes.example.com --revision FULL_COMMIT_SHA \
  --backup /var/backups/pretty-notebook/checkpoint-01 \
  --output /var/lib/pretty-notebook-restored-01
```

Repeat with `--apply` while the managed service remains stopped. Apply as root
or the planned state owner/group. Restored state belongs to the configured VPS
service account, or UID/GID 10001 for containers. Existing output locations,
symlinks, special files, incomplete receipts, changed/corrupt content, unsupported
schemas and mismatched code refuse completion.

The new directory contains `state/`, `environment`, `environment.original` and
`restore.json`. VPS environment paths are updated for the new state directory;
container internal paths remain fixed. The original environment is retained
exactly in `environment.original`. Original and failed state directories are
preserved.

Activation is deliberate: review the receipt and environment, update the
systemd `EnvironmentFile`/`ReadWritePaths` or container environment/bind mount to
the new paths, and start only the matching code/image. Verify health, content,
images, layout, account access, revoked credentials and inbox before retiring
any previous state. Restore the matching pre-upgrade checkpoint and old code
together when rolling back a migration.

## Interrupted operations

A failed/interrupted apply leaves `.incomplete` in its new output directory.
Such output cannot be restored or treated as ready. Preserve it for diagnosis
and retry into another new location after resolving the cause. File writes and
receipts are synced before completion. A successful restore prepares files;
it does not approve or perform hosted activation.

```{pnbp-cli-help} deploy backup
```

```{pnbp-cli-help} deploy restore
```
