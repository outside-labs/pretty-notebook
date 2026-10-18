"""Preview-first, stopped-site recovery into new private locations."""

from contextlib import closing, contextmanager
from dataclasses import replace
from importlib.metadata import version as package_version
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import tomllib

from .deployment import _run_checked, check_environment
from .web_state import CURRENT_VERSION, inspect_web_state

AUXILIARY = {'db.sqlite3-wal', 'db.sqlite3-shm', 'db.sqlite3-journal'}


def _location(value):
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise ValueError('Recovery locations must not be symlinks.')
    return path.resolve()


def _new_location(value, *sources):
    path = _location(value)
    if path.exists() or not path.parent.is_dir():
        raise ValueError('Choose a new output location with an existing parent directory.')
    for source in sources:
        source = _location(source)
        if path.is_relative_to(source) or source.is_relative_to(path):
            raise ValueError('Recovery output must be separate from existing state and backups.')
    return path


def _scan(root, *, copy_to=None, skip=frozenset()):
    """Read relative to directory descriptors and reject links/special files."""
    files, directories = {}, []
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    def unreadable(error):
        raise error
    try:
        for relative, names, filenames, directory in os.fwalk('.', dir_fd=descriptor, follow_symlinks=False, onerror=unreadable):
            prefix = Path(relative)
            if copy_to is not None:
                (copy_to / prefix).mkdir(mode=0o700, exist_ok=True)
            for name in names:
                if not stat.S_ISDIR(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode):
                    raise ValueError('Recovery trees must not contain symlinks or special files.')
                directories.append((prefix / name).as_posix())
            for name in sorted(filenames):
                if not stat.S_ISREG(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode):
                    raise ValueError('Recovery trees must contain regular files only.')
                relative_name = (prefix / name).as_posix()
                if relative_name in skip:
                    continue
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                target = None
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError('Recovery source is not a regular file.')
                    if copy_to is not None:
                        target_fd = os.open(copy_to / relative_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        target = os.fdopen(target_fd, 'wb')
                    digest = hashlib.sha256()
                    with os.fdopen(fd, 'rb', closefd=False) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                            if target is not None:
                                target.write(chunk)
                    after = os.fstat(fd)
                    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise ValueError('Recovery source changed while it was read; preserve the incomplete output.')
                    if target is not None:
                        target.flush()
                        os.fsync(target.fileno())
                    files[relative_name] = {'sha256': digest.hexdigest(), 'size': before.st_size}
                finally:
                    if target is not None:
                        target.close()
                    os.close(fd)
    finally:
        os.close(descriptor)
    return {'files': files, 'directories': sorted(directories)}


def _write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(data if isinstance(data, bytes) else data.encode('utf-8'))
        output.flush()
        os.fsync(output.fileno())


def _private_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
            raise ValueError('Recovery environment must be a private regular file within the 1 MiB bound.')
        contents = source.read(1024 * 1024 + 1)
        if len(contents) > 1024 * 1024:
            raise ValueError('Recovery environment grew beyond its supported bound.')
        return contents


def _code_identity(spec, profile):
    if profile == 'vps':
        revision = _run_checked(['git', '-C', str(spec.checkout), 'rev-parse', 'HEAD'], label='Backup code revision check')
        if _run_checked(['git', '-C', str(spec.checkout), 'status', '--porcelain', '--untracked-files=all'], label='Backup checkout check'):
            raise ValueError('Use a clean pinned checkout for recovery.')
        try:
            with (spec.checkout / 'pyproject.toml').open('rb') as source:
                version = tomllib.load(source)['project']['version']
        except (OSError, ValueError, KeyError) as error:
            raise ValueError('Matching application metadata is unavailable.') from error
        identity = {'revision': revision, 'version': version}
    elif profile == 'container':
        image = f'pretty-notebook:{spec.revision}'
        revision = _run_checked(['docker', 'image', 'inspect', '--format', '{{index .Config.Labels "org.opencontainers.image.revision"}}', image], label='Backup image revision check')
        image_id = _run_checked(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], label='Backup image identity check')
        version = _run_checked(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', image,
                                '-c', 'from importlib.metadata import version; print(version("pretty-notebook"))'], label='Backup image package check')
        identity = {'revision': revision, 'version': version, 'image_id': image_id}
    else:
        raise ValueError('Unknown recovery profile.')
    if (revision != spec.revision or version != package_version('pretty-notebook')
            or not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9.!+_-]{1,64}', version)):
        raise ValueError('Recovery requires the exact matching application revision and version.')
    return identity


def _require_stopped(spec, profile, code, *, match_image=True):
    if profile == 'vps':
        output = _run_checked(['systemctl', 'show', spec.service, '--property=LoadState,ActiveState,MainPID'], label='Stopped service check')
        fields = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        if fields.get('LoadState') != 'loaded' or fields.get('ActiveState') not in {'inactive', 'failed'} or fields.get('MainPID') != '0':
            raise ValueError('Stop the managed service completely before applying recovery.')
    else:
        state = json.loads(_run_checked(['docker', 'inspect', '--format', '{{json .State}}', spec.service], label='Stopped container check'))
        image_id = _run_checked(['docker', 'inspect', '--format', '{{.Image}}', spec.service], label='Stopped container image check')
        if not isinstance(state, dict) or state.get('Status') not in {'created', 'exited'} or state.get('Running') or state.get('Restarting') or state.get('Pid') != 0 or (match_image and image_id != code['image_id']):
            raise ValueError('Stop the matching managed container completely before applying recovery.')


@contextmanager
def _state_lock(root):
    import fcntl
    fd = os.open(root / 'site.lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('State coordination lock must be a regular file.')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('A state operation is running; stop the service before backup.') from error
        yield
    finally:
        os.close(fd)


def _environment_check(spec, profile):
    expected = {} if profile == 'vps' else {
        'PNBP_DATA_DIR': '/var/lib/pretty-notebook',
        'PNBP_DATABASE_URL': 'sqlite:///var/lib/pretty-notebook/db.sqlite3',
        'PNBP_PORT': str(spec.port), 'PNBP_WORKERS': str(spec.workers),
    }
    check_environment(spec, expected_values=expected)


def _snapshot_database(source, destination):
    _write(destination, b'')
    deadline = time.monotonic() + 30
    def progress(*args):
        if time.monotonic() > deadline:
            raise ValueError('Database snapshot timed out; preserve the incomplete output.')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot, pages=256, progress=progress, sleep=0.05)
    with destination.open('rb') as stream:
        os.fsync(stream.fileno())


def _finish(root, name, payload):
    receipt = json.dumps(payload, indent=2, sort_keys=True) + '\n'
    if len(receipt.encode('utf-8')) > 16 * 1024 * 1024:
        raise ValueError('Recovery receipt exceeds the supported 16 MiB bound; preserve the incomplete output.')
    _write(root / name, receipt)
    # Persist directory entries after all file contents and the receipt are durable.
    for directory in sorted((p for p in root.rglob('*') if p.is_dir()), reverse=True):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    (root / '.incomplete').unlink()
    for directory in (root, root.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def backup_site(spec, output, *, profile='vps', apply=False):
    source = _location(spec.data_dir)
    output = _new_location(output, source, spec.env_file)
    code = _code_identity(spec, profile)
    _environment_check(spec, profile)
    storage = inspect_web_state(source)
    report = {'operation': 'backup', 'apply': apply, 'output': str(output), 'revision': spec.revision,
              'version': code['version'], 'schema_version': storage['schema_version'], 'profile': profile}
    if not apply:
        return report
    _require_stopped(spec, profile, code)
    with _state_lock(source):
        before = _scan(source, skip={'db.sqlite3-shm'})
        environment = _private_bytes(spec.env_file)
        output.mkdir(mode=0o700)
        _write(output / '.incomplete', 'Backup is incomplete; do not restore.\n')
        (output / 'state').mkdir(mode=0o700)
        _scan(source, copy_to=output / 'state', skip={'db.sqlite3', *AUXILIARY})
        _snapshot_database(source / 'db.sqlite3', output / 'state/db.sqlite3')
        _write(output / 'environment', environment)
        _write(output / 'deployment.json', json.dumps(spec.to_dict(), sort_keys=True))
        inspect_web_state(output / 'state')
        if before != _scan(source, skip={'db.sqlite3-shm'}) or environment != _private_bytes(spec.env_file):
            raise ValueError('Source changed during backup; preserve the incomplete output and retry stopped.')
        if _code_identity(spec, profile) != code:
            raise ValueError('Application identity changed during backup.')
        _require_stopped(spec, profile, code)
        inventory = _scan(output, skip={'.incomplete'})
        _finish(output, 'manifest.json', {'format': 1, 'profile': profile, 'code': code,
                                         'schema_version': CURRENT_VERSION, 'inventory': inventory})
    return {**report, 'verified': True}


def verify_backup(path):
    root = _location(path)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError('Backup must be a private directory (mode 0700).')
    if (root / '.incomplete').exists():
        raise ValueError('Backup is incomplete; preserve it and use a verified backup.')
    try:
        manifest_path = root / 'manifest.json'
        if manifest_path.is_symlink() or manifest_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Backup receipt is invalid or exceeds the supported bound.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if (not isinstance(manifest, dict) or manifest.get('format') != 1 or manifest.get('profile') not in {'vps', 'container'}
                or manifest.get('schema_version') != CURRENT_VERSION
                or _scan(root, skip={'manifest.json'}) != manifest.get('inventory')):
            raise ValueError('Backup is incomplete, corrupt or unsupported.')
        if not {'environment', 'deployment.json'} <= set(manifest['inventory']['files']):
            raise ValueError('Backup is missing private configuration.')
        inspect_web_state(root / 'state')
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError, KeyError) as error:
        raise ValueError('Backup could not be verified; preserve it and inspect the private files locally.') from error
    return manifest


def _owner(spec, profile):
    if profile == 'container':
        return 10001, 10001
    import pwd
    try:
        user = pwd.getpwnam(spec.user)
    except KeyError as error:
        raise ValueError('The recovery service account is unavailable.') from error
    if user.pw_uid == 0:
        raise ValueError('Recovery state needs a non-root service account.')
    return user.pw_uid, user.pw_gid


def restore_site(spec, backup, output, *, profile='vps', apply=False):
    backup = _location(backup)
    output = _new_location(output, backup, spec.data_dir, spec.env_file)
    manifest = verify_backup(backup)
    code = _code_identity(spec, profile)
    if manifest['profile'] != profile or manifest['code'] != code:
        raise ValueError('Restore requires the exact backup profile, code version, revision and image identity.')
    deployment = json.loads((backup / 'deployment.json').read_text(encoding='utf-8'))
    if not isinstance(deployment, dict) or any(deployment.get(key) != spec.to_dict()[key] for key in ('domain', 'port', 'workers', 'prefix')):
        raise ValueError('Restore options must retain the backed-up domain, port, workers and prefix.')
    restored_spec = replace(spec, data_dir=output / 'state', env_file=output / 'environment')
    report = {'operation': 'restore', 'apply': apply, 'output': str(output), 'revision': spec.revision,
              'version': code['version'], 'profile': profile, 'activation_required': True}
    if not apply:
        return report
    _require_stopped(spec, profile, code, match_image=False)
    owner, group = _owner(spec, profile)
    if os.geteuid() != 0 and (owner, group) != (os.geteuid(), os.getegid()):
        raise ValueError('Apply restoration as root or the planned state owner/group.')
    output.mkdir(mode=0o700)
    _write(output / '.incomplete', 'Restoration is incomplete; do not activate.\n')
    (output / 'state').mkdir(mode=0o700)
    _scan(backup / 'state', copy_to=output / 'state')
    expected_state = {
        'files': {name.removeprefix('state/'): value for name, value in manifest['inventory']['files'].items() if name.startswith('state/')},
        'directories': [name.removeprefix('state/') for name in manifest['inventory']['directories'] if name.startswith('state/')],
    }
    if _scan(output / 'state') != expected_state:
        raise ValueError('Restored files differ from the verified checkpoint; preserve the incomplete output.')
    original_environment = _private_bytes(backup / 'environment').decode('utf-8')
    environment = original_environment
    if profile == 'vps':
        import shlex
        values = {'PNBP_DATA_DIR': str(output / 'state'), 'PNBP_DATABASE_URL': 'sqlite://' + str(output / 'state/db.sqlite3')}
        environment = '\n'.join(key + '=' + shlex.quote(values[key]) if (key := line.partition('=')[0].strip()) in values else line for line in environment.splitlines()) + '\n'
    _write(output / 'environment.original', original_environment)
    _write(output / 'environment', environment)
    _environment_check(restored_spec, profile)
    inspect_web_state(output / 'state')
    if verify_backup(backup) != manifest:
        raise ValueError('Backup changed during restoration; preserve the incomplete output.')
    _require_stopped(spec, profile, code, match_image=False)
    if _code_identity(spec, profile) != code:
        raise ValueError('Application identity changed during restoration.')
    for path in [output, output / 'state', *(output / 'state').rglob('*')]:
        os.chown(path, owner, group)
    _finish(output, 'restore.json', {'format': 1, 'code': code, 'state': str(output / 'state'),
                                    'environment': str(output / 'environment'), 'activation_required': True})
    return {**report, 'verified': True, 'state': str(output / 'state'), 'environment': str(output / 'environment')}
