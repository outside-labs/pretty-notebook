# Linux container deployment

The optional container profile supports Linux x86_64 with Docker Engine, Compose
2.30 or later, one local state directory, one Gunicorn instance with 1–4 workers,
and an existing host nginx TLS proxy. It uses the same application factory,
serialized migrations, owner bootstrap and local browser assets as the
[VPS profile](vps-deployment.md). Docker Desktop and multiple replicas are outside
this profile.

## Prepare a pinned plan

Choose a reviewed full commit SHA and dedicated host paths:

```bash
pnbp deploy plan --profile container --domain notes.example.com \
  --revision FULL_COMMIT_SHA
pnbp deploy init --profile container --domain notes.example.com \
  --revision FULL_COMMIT_SHA --output ./container-plan
```

`plan` writes nothing. `init` generates `compose.json`, `environment.example`,
`nginx.conf`, `build.sh`, a receipt and operating instructions. It preserves
identical bundles and refuses differing existing files. It does not create
secrets, change state ownership, activate services or claim the owner.

Set `--checkout`, `--data-dir`, `--env-file`, `--backup-dir`, `--port`, `--workers`
and `--prefix` as needed; reuse those options for `check` and `upgrade`.
The container uses the reviewed Python 3.14 base image pinned by digest and the
existing web dependency hash lock. The generated build script verifies that the
checkout matches the selected SHA and contains no local changes. Images remain
local and are tagged by that revision; this workflow does not publish images.

## Configure and start

Review the generated `README.txt`. Build from the dedicated clean checkout with
`bash build.sh`. Create an empty local bind-mount directory owned by UID/GID
10001 with mode 0700. Existing state needs a separate stopped-site migration;
setup never changes its ownership or contents.

Copy the environment template to the chosen private environment file with mode
0600. Set distinct random JWT and bootstrap secrets of at least 32 UTF-8 bytes.
The internal data path stays `/var/lib/pretty-notebook`, even when `--data-dir`
selects another host directory. Keep the private environment outside the checkout.
Compose reads values in raw mode, preserving literal dollar signs in secrets.

```bash
pnbp deploy check --profile container --domain notes.example.com \
  --revision FULL_COMMIT_SHA --require-bootstrap
docker compose --file ./container-plan/compose.json config --quiet
docker compose --file ./container-plan/compose.json up --detach --no-build --pull never
```

The container runs as UID/GID 10001 with a read-only root filesystem, dropped
capabilities and a temporary `/tmp`. The bind mount holds the complete persistent
state. Linux host networking lets Gunicorn bind only to host loopback and trust
the existing loopback TLS proxy. Review/install the generated nginx configuration
with your existing certificate, test it, and reload nginx explicitly.

Check Docker health and `pnbp deploy check --profile container ... --health`.
[Claim the owner](web.md#claim-the-initial-owner) explicitly. Remove the bootstrap token
from the environment and recreate the container after claiming it.

## Upgrade and recover

Generate `pnbp deploy upgrade --profile container` for the new full SHA into a new
bundle directory. Build the new image before stopping the running service.
Use the [verified recovery commands](backups.md) with `--profile container`.
Record the old image ID/revision and back up the complete stopped state,
private environment and proxy configuration. Stop the previous VPS/container
before starting the replacement; never run both on the same state directory.
The application performs serialized migrations when the new container starts.

Rerunning `up` reuses persistent state. A failed start leaves that state available
for diagnosis. For rollback, stop the failed container and restore the verified
pre-upgrade checkpoint into a new directory. Use the matching old image and
private environment, update the bind mount deliberately, then verify health and
content. Preserve the original and failed states; do not run old code directly
against a migrated database.

CI builds the pinned image, validates the generated Compose plan, claims a
synthetic owner, publishes a fixture, checks Host filtering, reruns setup and
verifies authentication/publication across two four-worker restarts.
The image and context use explicit source/resource allowlists and exclude local
state, credentials, archives and test fixtures. See Docker's
[build guidance](https://docs.docker.com/build/building/best-practices/) and
[Dockerfile reference](https://docs.docker.com/reference/dockerfile/).
