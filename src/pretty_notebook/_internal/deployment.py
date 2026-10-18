"""Reproducible Linux VPS bundles and bounded local deployment diagnostics."""

import hashlib
import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from urllib.request import Request, urlopen

from .routes import validate_prefix


@dataclass(frozen=True)
class DeploySpec:
    revision: str
    domain: str
    checkout: Path = Path('/opt/pretty-notebook')
    data_dir: Path = Path('/var/lib/pretty-notebook')
    env_file: Path = Path('/etc/pretty-notebook/environment')
    backup_dir: Path = Path('/var/backups/pretty-notebook')
    tls_cert: Path = Path('/etc/ssl/pretty-notebook/fullchain.pem')
    tls_key: Path = Path('/etc/ssl/pretty-notebook/privkey.pem')
    service: str = 'pretty-notebook'
    user: str = 'pretty-notebook'
    python: str = 'python3.14'
    port: int = 8000
    workers: int = 4
    prefix: str = ''

    def __post_init__(self):
        if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', self.revision):
            raise ValueError('Revision must be a full lowercase commit SHA.')
        labels = self.domain.split('.')
        if len(self.domain) > 253 or len(labels) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels):
            raise ValueError('Domain must be a lowercase DNS hostname without a scheme or port.')
        for name in ('service', 'user'):
            if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', getattr(self, name)):
                raise ValueError(f'Invalid deployment {name}.')
        if self.user == 'root':
            raise ValueError('Use a dedicated non-root service account.')
        for name in ('checkout', 'data_dir', 'env_file', 'backup_dir', 'tls_cert', 'tls_key'):
            value = Path(getattr(self, name))
            if not value.is_absolute() or len(value.parts) < 3 or '..' in value.parts or not re.fullmatch(r'/[A-Za-z0-9/_.-]+', str(value)):
                raise ValueError(f'{name} must be an absolute path without shell/systemd metacharacters.')
            object.__setattr__(self, name, value)
        directories = (self.checkout, self.data_dir, self.backup_dir)
        if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(directories) for b in directories[i + 1:]):
            raise ValueError('Checkout, data and backup directories must be separate.')
        if any(self.env_file.is_relative_to(path) for path in directories):
            raise ValueError('Environment file must be separate from code, data and backups.')
        if self.python not in ('python3.11', 'python3.14'):
            raise ValueError('Use supported Python 3.11 or 3.14.')
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError('Port must be from 1024 to 65535.')
        if type(self.workers) is not int or not 1 <= self.workers <= 4:
            raise ValueError('Workers must be from 1 to 4.')
        validate_prefix(self.prefix)

    def to_dict(self):
        return {key: str(value) if isinstance(value, Path) else value for key, value in asdict(self).items()}


def bundle(spec, operation='init', *, profile='vps'):
    if profile == 'container':
        from .containers import container_bundle
        return container_bundle(spec, operation)
    if profile != 'vps':
        raise ValueError('Unknown deployment profile.')
    if operation not in ('init', 'upgrade'):
        raise ValueError('Unknown deployment operation.')
    values = {key.upper(): str(value) for key, value in spec.to_dict().items()}
    values.update({key + '_SH': shlex.quote(value) for key, value in list(values.items())})
    values['PROXY'] = f'''        proxy_pass http://127.0.0.1:{spec.port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_connect_timeout 5s;
        proxy_read_timeout 35s;
        proxy_send_timeout 35s;'''
    values['PREFIX_REDIRECT'] = f'    location = {spec.prefix} {{ return 308 {spec.prefix}/; }}' if spec.prefix else ''
    resources = files('pretty_notebook').joinpath('resources/deploy')
    result = {}
    for name in ('service', 'nginx.conf', 'environment.example', 'common.sh', 'init.sh', 'upgrade.sh', 'rollback.sh', 'checkpoint.py'):
        template = resources.joinpath(name + '.tmpl').read_text(encoding='utf-8')
        rendered = re.sub(r'@([A-Z_]+)@', lambda match: values[match[1]], template)
        result[spec.service + '.service' if name == 'service' else name] = rendered
    manifest = {'format': 1, 'operation': operation, 'spec': spec.to_dict(),
                'files': {name: hashlib.sha256(content.encode()).hexdigest() for name, content in result.items()},
                'apply': f'sudo bash {operation}.sh',
                'requirements': ['Linux x86_64, systemd, nginx, git, curl and the selected Python',
                                 'An existing TLS certificate/key and a private configured environment file']}
    result['plan.json'] = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
    return result


def write_bundle(spec, output, *, operation='init', profile='vps'):
    output = Path(output).expanduser()
    if output.is_symlink():
        raise ValueError('Bundle directory must not be a symlink.')
    output = output.resolve()
    contents = bundle(spec, operation, profile=profile)
    for name, content in contents.items():
        path = output / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_text() != content)):
            raise ValueError(f'{name} already differs; choose an empty output directory.')
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    for name, content in contents.items():
        path = output / name
        if not path.exists():
            with path.open('x', encoding='utf-8') as target:
                target.write(content)
            path.chmod(0o700 if name.endswith('.sh') else 0o600)
    return {'output': str(output), 'operation': operation, 'revision': spec.revision,
            'apply': (f'Follow {output / "README.txt"}' if profile == 'container' else
                      f'sudo bash {shlex.quote(str(output / (operation + ".sh")))}')}


def _run_checked(arguments, *, cwd=None, label):
    try:
        result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f'{label} could not run.') from error
    if result.returncode:
        raise ValueError(f'{label} failed; inspect it locally without sharing credentials.')
    return result.stdout.strip()


def check_environment(spec, *, require_bootstrap=False, expected_values=None):
    path = spec.env_file
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Environment file must be a private regular file (mode 0600).')
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        match = re.fullmatch(r'([A-Z_][A-Z0-9_]*)=(.*)', line)
        if not match or match[1] in values:
            raise ValueError('Environment file contains an invalid or duplicate assignment.')
        try: parsed = shlex.split(match[2])
        except ValueError as error: raise ValueError('Environment file contains invalid quoting.') from error
        if len(parsed) > 1:
            raise ValueError('Environment values containing spaces must be quoted.')
        values[match[1]] = parsed[0] if parsed else ''
    expected_profile = {'PNBP_DATA_DIR': str(spec.data_dir),
                          'PNBP_DATABASE_URL': f'sqlite://{spec.data_dir / "db.sqlite3"}',
                          'PNBP_URL_PREFIX': spec.prefix, 'PNBP_ASSET_MODE': 'local', 'JWT_ALGO': 'HS256'}
    expected_profile.update(expected_values or {})
    for key, expected in expected_profile.items():
        if values.get(key, '') != expected: raise ValueError(f'Environment {key} does not match the deployment plan.')
    hosts = values.get('PNBP_ALLOWED_HOSTS', '').split(',')
    if spec.domain not in hosts or '*' in hosts:
        raise ValueError('Environment PNBP_ALLOWED_HOSTS must include the planned domain without a wildcard.')
    for key in ('JWT_SECRET', 'PNBP_BOOTSTRAP_TOKEN'):
        value = values.get(key, '')
        required = key == 'JWT_SECRET' or require_bootstrap or bool(value)
        if required and (len(value.encode()) < 32 or value.startswith('REPLACE_')):
            raise ValueError(f'Environment {key} requires a configured secret of at least 32 UTF-8 bytes.')
    return {'environment': 'ok'}


def check_deployment(spec, *, health=False, require_bootstrap=False):
    result = check_environment(spec, require_bootstrap=require_bootstrap)
    import pwd
    try:
        owner = pwd.getpwnam(spec.user).pw_uid
    except KeyError as error:
        raise ValueError('The planned service account does not exist.') from error
    state = spec.data_dir
    if owner == 0 or state.is_symlink() or not state.is_dir() or state.stat().st_mode & 0o077 or state.stat().st_uid != owner:
        raise ValueError('Persistent data must be a private directory owned by the non-root service account.')
    revision = _run_checked(['git', '-C', str(spec.checkout), 'rev-parse', 'HEAD'], label='Checkout revision check')
    if revision != spec.revision: raise ValueError('Checkout does not match the pinned revision.')
    _run_checked(['git', '-C', str(spec.checkout), 'diff', '--exit-code'], label='Checkout cleanliness check')
    python = str(spec.checkout / '.venv/bin/python')
    version = _run_checked([python, '-c', 'import sys; print("%s.%s" % sys.version_info[:2])'], label='Python version check')
    if version != spec.python.removeprefix('python'): raise ValueError('Virtual environment uses a different Python version.')
    _run_checked([python, '-m', 'pip', 'check'], label='Dependency check')
    _run_checked([python, 'install_assets.py', '--check'], cwd=spec.checkout / 'apps/web', label='Local asset check')
    result.update(revision=revision, dependencies='ok', assets='ok', python=version)
    if health:
        try:
            request = Request(f'http://127.0.0.1:{spec.port}/healthz', headers={'Host': spec.domain})
            with urlopen(request, timeout=5) as response:
                if json.loads(response.read(4096)) != {'status': 'ok'}: raise ValueError('Invalid health response.')
        except (OSError, ValueError) as error:
            raise ValueError('Loopback health check failed.') from error
        result['health'] = 'ok'
    return result
