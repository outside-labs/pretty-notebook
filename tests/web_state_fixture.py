"""Synthetic persistent state built from the actual server's SQL declarations."""

import ast
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def constant(path, name):
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('SQL declaration not found: ' + name)


def create_state(root):
    root.mkdir(mode=0o700)
    pages = root / 'pages'
    images = root / 'images'
    blobs = pages / '.blobs'
    blobs.mkdir(parents=True, mode=0o700)
    images.mkdir(mode=0o700)
    body = b'<p>Synthetic retained publication</p>'
    digest = hashlib.sha256(body).hexdigest()
    (blobs / (digest + '.html')).write_bytes(body)
    (images / 'fixture.png').write_bytes(b'synthetic-image')
    (root / 'web-settings.json').write_text('{"TITLE":"Synthetic site"}')
    with closing(sqlite3.connect(root / 'db.sqlite3')) as connection:
        for source, name in (('schema.py', 'BASE_SCHEMA'), ('catalog.py', 'CATALOG_SCHEMA')):
            for statement in constant(ROOT / 'apps/web/api' / source, name):
                connection.execute(statement)
        connection.execute(constant(ROOT / 'apps/web/api/schema.py', 'HISTORY_SCHEMA'))
        connection.executemany('INSERT INTO pnbp_schema_migrations (version,name,applied_at) VALUES (?, ?, ?)', [(1, 'base-schema', '2026-01-01'), (2, 'publication-catalog', '2026-01-01')])
        connection.execute("INSERT INTO user VALUES (1, 'owner', 'synthetic-password-hash', 'synthetic-revocation-uuid')")
        connection.execute("INSERT INTO formsubmission (form_name,payload) VALUES ('contact', '{\"email_message\":\"Synthetic message\"}')")
        connection.execute("INSERT INTO pnbp_notebooks VALUES ('default', 'notebook-id')")
        connection.execute("INSERT INTO pnbp_notes VALUES ('note-id','notebook-id','/fixture','[]','Fixture','public',1)")
        connection.execute("INSERT INTO pnbp_revisions VALUES ('note-id',1,?,NULL,?,NULL,'[]','2026-01-01')", (digest, digest))
        connection.commit()
    for path in root.rglob('*'):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return root
