"""Generate the optional single-host Linux container profile without activation."""

import hashlib
import json
import shlex
from urllib.request import Request, urlopen

from .deployment import bundle, check_environment, _run_checked


def container_bundle(spec, operation='init'):
    if operation not in ('init', 'upgrade'):
        raise ValueError('Unknown deployment operation.')
    if spec.python != 'python3.14':
        raise ValueError('The container profile uses the pinned Python 3.14 image.')
    image = f'pretty-notebook:{spec.revision}'
    service = {
        'image': image, 'pull_policy': 'never', 'container_name': spec.service,
        'network_mode': 'host', 'user': '10001:10001', 'read_only': True,
        'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
        'tmpfs': ['/tmp:rw,noexec,nosuid,size=64m,mode=1777'],
        'volumes': [{'type': 'bind', 'source': str(spec.data_dir), 'target': '/var/lib/pretty-notebook',
                     'bind': {'create_host_path': False}}],
        'env_file': [{'path': str(spec.env_file), 'format': 'raw'}],
        'environment': {'PNBP_PORT': str(spec.port), 'PNBP_WORKERS': str(spec.workers)},
        'restart': 'unless-stopped', 'stop_grace_period': '45s',
    }
    environment = bundle(spec)['environment.example'].replace(str(spec.data_dir), '/var/lib/pretty-notebook')
    environment += f'PNBP_PORT={spec.port}\nPNBP_WORKERS={spec.workers}\n'
    build = f'''#!/usr/bin/env bash
set -Eeuo pipefail
checkout={shlex.quote(str(spec.checkout))}
revision={shlex.quote(spec.revision)}
[[ "$(git -C "$checkout" rev-parse HEAD)" == "$revision" ]] || {{ echo 'Checkout does not match the pinned revision.' >&2; exit 1; }}
[[ -z "$(git -C "$checkout" status --porcelain --untracked-files=all)" ]] || {{ echo 'Preserve checkout changes before building.' >&2; exit 1; }}
docker build --platform linux/amd64 --build-arg "PNBP_REVISION=$revision" --file "$checkout/apps/web/container/Dockerfile" --tag {shlex.quote(image)} "$checkout"
'''
    instructions = f'''Linux x86_64, Docker Engine and Compose 2.30+ only. Review all files before use.
This bundle neither creates secrets nor changes a service, proxy or persistent state.
Use one Gunicorn instance (1–4 workers), one private local state root and a host TLS nginx proxy.

1. Check out {spec.revision} in {spec.checkout}; preserve any existing checkout changes.
2. Run bash build.sh. The build verifies that checkout and uses the reviewed Dockerfile/base digest and hash-locked wheels.
3. For initial setup only, create an EMPTY {spec.data_dir} owned by UID/GID 10001, mode 0700.
   Do not chown or overwrite an existing state root. Restore/upgrade it separately after stopping the old service.
4. Copy environment.example to {spec.env_file}, mode 0600, with distinct private secrets.
   Never copy the environment into the checkout or image. Check with pnbp deploy check --profile container and the same plan options.
5. Validate: docker compose --file compose.json config --quiet
6. Stop the existing instance before upgrades. Back up its COMPLETE state and environment plus its image ID/revision before continuing.
7. Start: docker compose --file compose.json up --detach --no-build --pull never
   Wait for healthy status and verify the configured loopback /healthz. On failure, stop the container and retain state/logs for diagnosis.
8. Install/review nginx.conf on the host with your existing TLS certificate. Test nginx configuration before reloading.
9. Claim the owner explicitly, remove PNBP_BOOTSTRAP_TOKEN and recreate the container with the revised environment.

Rerunning up reuses the bind-mounted state; no files are replaced by bundle generation.
Startup runs the established serialized schema migrations. Never run a second VPS/container against the same data root.
For rollback, stop the new container, restore the verified pre-upgrade state and matching private environment INTO A NEW LOCATION,
then use the saved old image ID/revision with that restored location. Do not start old code on a migrated database.
Keep the original and failed state until recovery is verified. Never use compose down --volumes as a backup/restore step.
Container host networking is deliberate: Gunicorn binds only 127.0.0.1:{spec.port}; host nginx remains the trusted TLS proxy.
'''
    result = {'compose.json': json.dumps({'name': spec.service, 'services': {'notebook': service}}, indent=2) + '\n',
              'environment.example': environment, 'nginx.conf': bundle(spec)['nginx.conf'],
              'build.sh': build, 'README.txt': instructions}
    manifest = {'format': 1, 'profile': 'container', 'operation': operation, 'spec': spec.to_dict(),
                'image': image, 'files': {name: hashlib.sha256(content.encode()).hexdigest() for name, content in result.items()},
                'apply': 'Review README.txt; activation is a separate stopped-site operation.',
                'requirements': ['Linux x86_64, Docker Engine, Compose 2.30+, host nginx and existing TLS',
                                 'Private local bind mount owned by UID/GID 10001; one instance only']}
    result['plan.json'] = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
    return result


def check_container(spec, *, health=False, require_bootstrap=False):
    container_bundle(spec)
    if spec.data_dir.is_symlink() or not spec.data_dir.is_dir():
        raise ValueError('Container state must be an existing private directory.')
    metadata = spec.data_dir.stat()
    if metadata.st_mode & 0o077 or metadata.st_uid != 10001 or metadata.st_gid != 10001:
        raise ValueError('Container state must have mode 0700 and UID/GID 10001.')
    result = check_environment(spec, require_bootstrap=require_bootstrap, expected_values={
        'PNBP_DATA_DIR': '/var/lib/pretty-notebook',
        'PNBP_DATABASE_URL': 'sqlite:///var/lib/pretty-notebook/db.sqlite3',
        'PNBP_WORKERS': str(spec.workers), 'PNBP_PORT': str(spec.port),
    })
    image = f'pretty-notebook:{spec.revision}'
    revision = _run_checked(['docker', 'image', 'inspect', '--format',
                             '{{index .Config.Labels "org.opencontainers.image.revision"}}', image], label='Container image revision check')
    if revision != spec.revision:
        raise ValueError('Container image does not match the pinned revision.')
    _run_checked(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', image, '-m', 'pip', 'check'], label='Container dependency check')
    result.update(profile='container', revision=revision, dependencies='ok')
    if health:
        try:
            with urlopen(Request(f'http://127.0.0.1:{spec.port}/healthz', headers={'Host': spec.domain}), timeout=5) as response:
                if json.loads(response.read(4096)) != {'status': 'ok'}:
                    raise ValueError('Invalid health response.')
        except (OSError, ValueError) as error:
            raise ValueError('Loopback health check failed.') from error
        result['health'] = 'ok'
    return result
