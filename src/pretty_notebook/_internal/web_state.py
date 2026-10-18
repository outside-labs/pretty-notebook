"""Read-only validation shared by web diagnostics and stopped-site recovery."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

MIGRATION_NAMES = {1: 'base-schema', 2: 'publication-catalog', 3: 'scoped-permissions'}
CURRENT_VERSION = max(MIGRATION_NAMES)
BASE_COLUMNS = {
    'user': {'id', 'username', 'password_hash', 'tok_uuid'},
    'formsubmission': {'id', 'form_name', 'payload', 'created_at'},
}
CATALOG_COLUMNS = {
    'pnbp_notebooks': {'slot', 'id'},
    'pnbp_notes': {'id', 'notebook_id', 'canonical_route', 'aliases', 'title', 'visibility', 'current_revision'},
    'pnbp_revisions': {'note_id', 'revision', 'body_hash', 'source_hash', 'rendered_hash', 'renderer_fingerprint', 'feature_flags', 'published_at'},
}

PERMISSION_COLUMNS = {
    'pnbp_roles': {'user_id', 'role'},
    'pnbp_grants': {'user_id', 'notebook', 'permission'},
    'pnbp_credentials': {'id', 'user_id', 'digest', 'generation', 'scopes', 'notebook', 'expires_at'},
}


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_web_state(root, *, allow_new=False, allow_pending=False):
    """Validate integrity, schema and every retained body without returning contents."""
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('State must be an existing directory without symlinks.')
    database = root / 'db.sqlite3'
    if not database.exists() and allow_new and not any(root.iterdir()):
        return {'state': 'new', 'schema_version': None, 'migration_needed': True}
    if database.is_symlink() or not database.is_file():
        raise ValueError('State database is missing or is not a regular file.')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('State database failed integrity validation.')
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version = 0
            if 'pnbp_schema_migrations' in tables:
                history = connection.execute('SELECT version,name FROM pnbp_schema_migrations ORDER BY version').fetchall()
                if history != [(number, MIGRATION_NAMES.get(number)) for number in range(1, len(history) + 1)] or len(history) > CURRENT_VERSION:
                    raise ValueError('State migration history is unsupported or inconsistent.')
                version = len(history)
            if version != CURRENT_VERSION and not allow_pending:
                raise ValueError('State schema does not match this application; use matching code and a verified backup.')
            required = {**BASE_COLUMNS, **(CATALOG_COLUMNS if version >= 2 else {}), **(PERMISSION_COLUMNS if version >= 3 else {})}
            for table, columns in required.items():
                found = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                if not columns <= found:
                    raise ValueError('State contains an incomplete application schema.')
            if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('State contains broken catalog references.')
            blobs = 0
            if version >= 2:
                if connection.execute('SELECT 1 FROM pnbp_notes n LEFT JOIN pnbp_revisions r ON n.id=r.note_id AND n.current_revision=r.revision WHERE r.note_id IS NULL LIMIT 1').fetchone():
                    raise ValueError('State contains a missing current publication revision.')
                directory = root / 'pages' / '.blobs'
                if directory.is_symlink() or directory.parent.is_symlink():
                    raise ValueError('Publication storage must not use symlink directories.')
                for digest, in connection.execute('SELECT DISTINCT body_hash FROM pnbp_revisions'):
                    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                        raise ValueError('State contains an invalid publication digest.')
                    path = directory / (digest + '.html')
                    if path.is_symlink() or not path.is_file() or checksum(path) != digest:
                        raise ValueError('A retained publication blob is missing or corrupt.')
                    blobs += 1
            counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in ('user', 'formsubmission')}
        for name in ('pages', 'images'):
            if (root / name).is_symlink() or not (root / name).is_dir():
                raise ValueError('Persistent page/image directories are missing or symlinked.')
        settings = root / 'web-settings.json'
        if settings.is_symlink() or not settings.is_file() or not isinstance(json.loads(settings.read_text(encoding='utf-8')), dict):
            raise ValueError('Persistent web settings are missing or invalid.')
    except (OSError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('State could not be read or verified; inspect the private files locally.') from error
    return {'state': 'ok', 'schema_version': version, 'migration_needed': version < CURRENT_VERSION,
            'retained_blobs': blobs, 'users': counts['user'], 'inbox_messages': counts['formsubmission']}
