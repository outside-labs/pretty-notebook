"""Ordered SQLite upgrades with private, consistent pre-migration backups."""

import asyncio
import hashlib
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from tortoise import connections
from tortoise.backends.sqlite.client import SqliteClient
from tortoise.transactions import in_transaction
from .catalog import CATALOG_SCHEMA
from .permissions import PERMISSION_SCHEMA
from .notebooks import OWNERSHIP_SCHEMA

from pretty_notebook._internal.web_state import CURRENT_VERSION, BASE_COLUMNS, CATALOG_COLUMNS, MIGRATION_NAMES, PERMISSION_COLUMNS
BASE_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS "user" (
        "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        "username" VARCHAR(50) NOT NULL UNIQUE,
        "password_hash" VARCHAR(128) NOT NULL,
        "tok_uuid" TEXT NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS "formsubmission" (
        "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        "form_name" VARCHAR(64) NOT NULL,
        "payload" JSON NOT NULL,
        "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''',
)
MIGRATIONS = {1: (MIGRATION_NAMES[1], BASE_SCHEMA), 2: (MIGRATION_NAMES[2], CATALOG_SCHEMA), 3: (MIGRATION_NAMES[3], PERMISSION_SCHEMA), 4: (MIGRATION_NAMES[4], OWNERSHIP_SCHEMA)}
HISTORY_SCHEMA = '''CREATE TABLE IF NOT EXISTS pnbp_schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    backup_path TEXT,
    backup_sha256 TEXT
)'''


def _backup(filename, version):
    """SQLite's backup API includes committed WAL state in one snapshot."""
    database = Path(filename).expanduser().resolve()
    directory = database.parent / "migration-backups"
    if directory.is_symlink():
        raise RuntimeError("Migration backup directory must not be a symlink.")
    directory.mkdir(mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f"{database.name}-from-v{version}-", suffix=".sqlite3", dir=directory)
    os.close(fd)
    path = Path(name)
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(path)) as backup:
                original.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Migration database backup failed integrity validation.")
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return str(path), hashlib.sha256(path.read_bytes()).hexdigest()
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def _validate_base(connection):
    for table, required in BASE_COLUMNS.items():
        rows = await connection.execute_query_dict(f'PRAGMA table_info("{table}")')
        if not required <= {row["name"] for row in rows}:
            raise RuntimeError(f"Unsupported legacy {table} schema; preserve state and restore a supported backup.")


async def _apply_migration(connection, version):
    for statement in MIGRATIONS[version][1]:
        await connection.execute_query(statement)
    await _validate_base(connection)
    if version >= 2:
        await _validate_catalog(connection)
    if version >= 3:
        await _validate_permissions(connection)
    if version >= 4:
        await _validate_ownership(connection)


async def _validate_catalog(connection):
    for table, required in CATALOG_COLUMNS.items():
        rows = await connection.execute_query_dict(f'PRAGMA table_info("{table}")')
        if not required <= {row["name"] for row in rows}:
            raise RuntimeError("Invalid publication catalog schema; restore a verified backup.")
    if await connection.execute_query_dict("PRAGMA foreign_key_check"):
        raise RuntimeError("Invalid publication catalog references; restore a verified backup.")


async def _validate_permissions(connection):
    for table, required in PERMISSION_COLUMNS.items():
        rows = await connection.execute_query_dict(f'PRAGMA table_info("{table}")')
        if not required <= {row["name"] for row in rows}:
            raise RuntimeError("Invalid permission schema; restore a verified backup.")


async def _validate_ownership(connection):
    rows = await connection.execute_query_dict("PRAGMA table_info(pnbp_notebooks)")
    if "owner_id" not in {row["name"] for row in rows}:
        raise RuntimeError("Invalid notebook ownership schema; restore a verified backup.")


async def migrate():
    """Upgrade before serving requests under the shared host-level writer lock."""
    connection = connections.get("default")
    if not isinstance(connection, SqliteClient):
        raise RuntimeError("Versioned server state supports SQLite only.")
    tables = {row["name"] for row in await connection.execute_query_dict("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "pnbp_schema_migrations" in tables:
        columns = await connection.execute_query_dict("PRAGMA table_info(pnbp_schema_migrations)")
        if not {"version", "name", "applied_at", "backup_path", "backup_sha256"} <= {row["name"] for row in columns}:
            raise RuntimeError("Invalid migration history schema; preserve the database and restore a verified backup.")
        rows = await connection.execute_query_dict("SELECT version, name FROM pnbp_schema_migrations ORDER BY version")
        versions = [row["version"] for row in rows]
        if any(type(version) is not int or version < 1 or version > CURRENT_VERSION for version in versions):
            raise RuntimeError("Unsupported server schema version; use the matching application and backup.")
        if versions != list(range(1, len(versions) + 1)) or any(row["name"] != MIGRATIONS[row["version"]][0] for row in rows):
            raise RuntimeError("Inconsistent migration history; preserve the database and restore a verified backup.")
        version = len(versions)
    else:
        version = 0
    if version == CURRENT_VERSION:
        await _validate_base(connection)
        await _validate_catalog(connection)
        await _validate_permissions(connection)
        await _validate_ownership(connection)
        return {"version": version, "backup_path": None, "backup_sha256": None}

    backup_path = backup_hash = None
    if connection.filename != ":memory:" and tables - {"sqlite_sequence"}:
        backup_path, backup_hash = await asyncio.to_thread(_backup, connection.filename, version)
    # SQLite's table-rebuild procedure disables FK enforcement before BEGIN,
    # validates every reference before commit, then restores enforcement.
    # https://www.sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes
    foreign_keys = await connection.execute_query_dict("PRAGMA foreign_keys")
    rebuild = version < 4 and bool(foreign_keys[0]['foreign_keys'])
    if rebuild:
        await connection.execute_query("PRAGMA foreign_keys=OFF")
    try:
        async with in_transaction() as transaction:
            await transaction.execute_query(HISTORY_SCHEMA)
            for target in range(version + 1, CURRENT_VERSION + 1):
                await _apply_migration(transaction, target)
                await transaction.execute_query(
                    "INSERT INTO pnbp_schema_migrations (version, name, applied_at, backup_path, backup_sha256) VALUES (?, ?, ?, ?, ?)",
                    [target, MIGRATIONS[target][0], datetime.now(UTC).isoformat(), backup_path, backup_hash],
                )
    finally:
        if rebuild:
            await connection.execute_query("PRAGMA foreign_keys=ON")
    return {"version": CURRENT_VERSION, "backup_path": backup_path, "backup_sha256": backup_hash}
