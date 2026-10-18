# Diagnostics

`pnbp doctor` checks the selected local notebook without creating configuration,
identities, probe files or derived content. Use the usual global `--notebook` or
`--profile` selection. `--json` produces a bounded report with `ok` and `checks`;
each check has a name, `ok`/`warning`/`error` status and a fixed diagnostic message.
Errors exit 1. Warnings, including an optional identity index that has not been
initialized, leave the command successful.

```bash
pnbp --notebook ~/notes doctor
pnbp --notebook ~/notes doctor --json
```

Checks cover runtime package availability, settings loading, directory access,
private credential-file permissions, identity consistency and the configured
renderer. Reports exclude note text, credentials, API URLs and raw exception
messages. A write-access check uses filesystem access metadata; it does not
promise that a subsequent save will succeed after permissions or files change.
Use `identity status` to inspect a specific identity-repair plan locally.

## Web state

`pnbp deploy check` combines the existing environment, pinned code/package,
asset and optional health checks with read-only state validation. The
[container variant](container-deployment.md) uses `--profile container`.

State validation checks SQLite integrity, ordered migration history, required
schema columns, foreign-key/current-revision references, every retained
publication body and its SHA256 digest, persistent directories and settings.
The result contains counts and schema status, never account records, inbox
messages or publication contents. An empty first-install state reports `new`;
an older supported schema reports that migration is needed. Diagnostics never
apply migrations. Unknown history, incomplete databases and missing/corrupt
bodies fail the check.

```{pnbp-cli-help} doctor
```
