# VPS deployment and upgrades (0.10)

`pnbp deploy` prepares inspectable Linux VPS bundles for the
[supported web profile](web.md). It uses systemd and nginx, one dedicated service
account, four Gunicorn Uvicorn workers, one local SQLite database, and one owning
notebook. The web app still comes from a reviewed repository checkout.
Generating a bundle neither connects to a VPS nor starts services.

## Plan and initialize

Choose a **full reviewed commit SHA** containing the 0.10 changes. A moving
branch name or an arbitrary shell expression is rejected. First inspect the
plan, then write the same configuration into a private bundle directory:

```bash
pnbp deploy plan --revision FULL_COMMIT_SHA --domain notes.example.com
pnbp deploy init --revision FULL_COMMIT_SHA --domain notes.example.com \
  --output ./vps-setup
```

The defaults are `/opt/pretty-notebook` for code, `/var/lib/pretty-notebook` for
state, `/etc/pretty-notebook/environment` for configuration, and
`/var/backups/pretty-notebook` for private checkpoints. `--checkout`,
`--data-dir`, `--env-file`, `--backup-dir`, `--service`, `--user`, `--python`,
`--port`, `--workers`, `--prefix`, `--tls-cert` and `--tls-key` are configurable.
Use Python 3.11 or 3.14 and 1–4 workers; four is the default. Code, state,
configuration and backups must remain separate. Paths reject shell/systemd
metacharacters. Keep code/state outside protected home and temporary directories
when using the supplied unit's `ProtectHome` and `PrivateTmp` settings.

The bundle contains a service unit, an nginx configuration, an environment
example, setup/upgrade/rollback scripts, a checkpoint verifier, and `plan.json`
with configuration and file hashes. Repeating generation with the same inputs
is harmless. A differing existing file stops generation before overwriting any
owner edits; use a new bundle directory for a new revision or configuration.
The installed wheel contains these templates too.

On the VPS, install systemd, nginx, git, curl and the chosen Python with venv/pip
support using the distribution's package manager. Supply an existing TLS
certificate and key at the planned paths; certificate issuance and DNS changes
remain the operator's setup. Copy `environment.example` to the planned private
file with mode **0600**, then configure two distinct random secrets of at least
32 UTF-8 bytes. The script never creates, prints or replaces these secrets.
Review the bundle before running its privileged setup on the target host:

```bash
sudo bash ./vps-setup/init.sh
```

Setup creates a dedicated service account and private data root when absent,
checks out the pinned commit, installs the hash-locked dependencies and editable
core package, validates assets/configuration, and installs the service/proxy.
Gunicorn listens only on loopback. nginx provides HTTPS, request limits, finite
timeouts and forwarded-header replacement. All static/dynamic assets stay behind
the application, including persistent owner stylesheets.

Rerunning setup at the same revision preserves state and secrets. A running
service must match the generated service/proxy before an idempotent health check;
changing an existing revision requires an upgrade bundle. Claim the initial
owner through the [documented bootstrap workflow](web.md#claim-the-initial-owner),
remove the bootstrap token, and restart the service.

## Check and upgrade in place

`pnbp deploy check` validates private environment settings, the checkout revision,
Python version, dependencies and reviewed local assets. Add `--health` for a
bounded loopback health request or `--require-bootstrap` before the first owner
claim. Diagnostics report setting names and status without secret values.
Pass the same path/profile options used by the service.

```bash
pnbp deploy check --revision CURRENT_COMMIT_SHA --domain notes.example.com --health
pnbp deploy upgrade --revision NEW_REVIEWED_COMMIT_SHA --domain notes.example.com \
  --output ./vps-upgrade
sudo bash ./vps-upgrade/upgrade.sh
```

Upgrades refuse a dirty checkout, fetch the explicit commit before stopping the
service, and then preserve the entire stopped state root, environment file, old
revision, dependency lock and service/proxy configuration. The checkpoint
verifier checks SQLite integrity and records hashes for every file. The script
installs the new revision, verifies its configuration/dependencies/assets,
starts the service (which runs coordinated schema migrations), checks health and
reloads nginx. Keep the printed checkpoint path private.

A failed upgrade stops the application and retains its checkpoint and failed
state. Repair a configuration problem and retry deliberately, or restore the
matching code and complete state with the reviewed rollback script:

```bash
sudo bash ./vps-upgrade/rollback.sh /var/backups/pretty-notebook/PRINTED_CHECKPOINT
```

Rollback verifies the checkpoint before moving current state, preserves the
failed state/environment separately, restores the old revision and matching
state/environment/service/proxy, installs that revision's locked dependencies,
and checks health. This deliberately restores credential and database state
from the checkpoint; do not mix snapshots. Check owner authentication, token
revocation, inbox messages, images, CSS and public pages after recovery. The
separate [OPS-03 task](https://github.com/wispsy/pretty-notebook/issues/94)
retains broader standalone backup/restore tooling.

This is a **stopped-service upgrade**, with brief downtime. It does not claim
zero-downtime rolling upgrades across different schema/application versions.
Once a reviewed merged revision passes CI, the same generated upgrade bundle
can be used by an operator's existing continuous-delivery workflow. The command
never configures deployment credentials or an external delivery service.

The generated files follow [Gunicorn deployment guidance](https://gunicorn.org/deploy/),
[systemd execution settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html),
and nginx's [proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html) and
[request-limit](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html) contracts.
Linux CI parses generated systemd/nginx configuration; the web suite exercises
real four-worker fresh/legacy startup and restart. Live DNS/TLS, service-account
permissions and clean-host provisioning still require verification on the target VPS.

The pinned Gunicorn's optional administration socket is explicitly disabled with
`--no-control-socket`, so startup creates no implicit state in the service user's
home. Administration uses systemd. See [Gunicorn control settings](https://gunicorn.org/reference/settings/#control_socket_disable).
