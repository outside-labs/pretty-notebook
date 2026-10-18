import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from stat import S_IMODE

import jwt
import pytest
from api import auth_api, schema
from fastapi.testclient import TestClient
from main import create_app
from passlib.hash import bcrypt


def seed_legacy(database, credentials):
    password = bcrypt.hash(credentials["password_hash"])
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript('''
            CREATE TABLE "user" (
                "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                "username" VARCHAR(50) NOT NULL UNIQUE,
                "password_hash" VARCHAR(128) NOT NULL,
                "tok_uuid" TEXT NOT NULL
            );
            CREATE TABLE "formsubmission" (
                "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                "form_name" VARCHAR(64) NOT NULL,
                "payload" JSON NOT NULL,
                "created_at" TIMESTAMP NOT NULL
            );
        ''')
        connection.execute('INSERT INTO "user" VALUES (?, ?, ?, ?)', [1, credentials["username"], password, "existing-token-state"])
        connection.execute('INSERT INTO "user" VALUES (?, ?, ?, ?)', [4, "reader", password, "other-token-state"])
        connection.execute('INSERT INTO "formsubmission" VALUES (?, ?, ?, ?)', [7, "contact", json.dumps({"email_message": "Preserve café"}), "2026-10-01 12:00:00+00:00"])
        connection.commit()
    return password


def legacy_rows(database):
    with closing(sqlite3.connect(database)) as connection:
        return {
            "users": connection.execute('SELECT * FROM "user" ORDER BY id').fetchall(),
            "messages": connection.execute('SELECT * FROM "formsubmission" ORDER BY id').fetchall(),
            "sequences": connection.execute("SELECT * FROM sqlite_sequence ORDER BY name").fetchall(),
        }


def token(token_id):
    now = datetime.now(UTC)
    return jwt.encode({"sub": "1", "tok_uuid": token_id, "iat": now, "exp": now + timedelta(hours=1)}, auth_api.JWT_SECRET, algorithm="HS256")


def test_legacy_upgrade_preserves_state_tokens_messages_and_backup(tmp_path, web_storage, root_credentials, bootstrap_headers):
    database = tmp_path / "legacy.sqlite3"
    seed_legacy(database, root_credentials)
    before = legacy_rows(database)
    (web_storage.pages / "legacy.html").write_text("Legacy body {{ 7 * 7 }}")
    app = create_app(db_url=f"sqlite://{database}")
    with TestClient(app) as client:
        assert client.get("/api/users/me", headers={"Authorization": f"Bearer {token('existing-token-state')}"}).json()["id"] == 1
        revoked = client.get("/api/users/me", headers={"Authorization": f"Bearer {token('superseded-token-state')}"})
        assert revoked.status_code == 401
        assert "revoked" in revoked.json()["detail"]
        inbox = client.get("/api/forms/contact/submissions", headers={"Authorization": f"Bearer {token('existing-token-state')}"})
        assert inbox.json()[0]["id"] == 7
        assert inbox.json()[0]["payload"]["email_message"] == "Preserve café"
        assert "{{ 7 * 7 }}" in client.get("/legacy").text
        assert client.post("/api/users", json={"username": "new-owner", "password_hash": "another sufficiently long password"}, headers=bootstrap_headers).status_code == 401
        report = app.state.schema_migration
        assert report["version"] == schema.CURRENT_VERSION
    assert legacy_rows(database) == before
    backup = Path(report["backup_path"])
    assert S_IMODE(backup.stat().st_mode) == 0o600
    assert report["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert legacy_rows(backup) == before
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version, name, backup_path FROM pnbp_schema_migrations ORDER BY version").fetchall() == [(number, name, str(backup)) for number, name in schema.MIGRATION_NAMES.items()]
    with TestClient(create_app(db_url=f"sqlite://{database}")) as restarted:
        assert restarted.app.state.schema_migration["backup_path"] is None
        assert restarted.get("/healthz").status_code == 200
    assert list(backup.parent.glob("*.sqlite3")) == [backup]


def test_fresh_database_records_version_without_unnecessary_backup(tmp_path, web_storage):
    database = tmp_path / "fresh.sqlite3"
    with TestClient(create_app(db_url=f"sqlite://{database}")) as client:
        assert client.app.state.schema_migration == {"version": schema.CURRENT_VERSION, "backup_path": None, "backup_sha256": None}
        assert client.get("/healthz").status_code == 200
    assert not (tmp_path / "migration-backups").exists()


def test_failed_schema_changes_roll_back_and_leave_backup(tmp_path, web_storage, root_credentials, monkeypatch):
    database = tmp_path / "legacy.sqlite3"
    seed_legacy(database, root_credentials)
    before = legacy_rows(database)
    async def fail_migration(connection, version):
        await connection.execute_query("CREATE TABLE transient_upgrade (id INTEGER)")
        raise RuntimeError("simulated schema failure")
    monkeypatch.setattr(schema, "_apply_migration", fail_migration)
    with pytest.raises(RuntimeError, match="simulated schema failure"):
        with TestClient(create_app(db_url=f"sqlite://{database}")):
            pass
    assert legacy_rows(database) == before
    with closing(sqlite3.connect(database)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "transient_upgrade" not in tables
    assert "pnbp_schema_migrations" not in tables
    backup, = (tmp_path / "migration-backups").glob("*.sqlite3")
    assert legacy_rows(backup) == before


@pytest.mark.parametrize("version,name", [(999, "future-schema"), (0, "base-schema"), (1, "unexpected-name")])
def test_unknown_or_inconsistent_history_refuses_startup(tmp_path, web_storage, version, name):
    database = tmp_path / "history.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE pnbp_schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT, backup_path TEXT, backup_sha256 TEXT)")
        connection.execute("INSERT INTO pnbp_schema_migrations (version, name) VALUES (?, ?)", [version, name])
        connection.commit()
    with pytest.raises(RuntimeError, match="schema version|migration history"):
        with TestClient(create_app(db_url=f"sqlite://{database}")):
            pass
    assert not (tmp_path / "migration-backups").exists()


def test_incompatible_legacy_schema_is_backed_up_and_not_replaced(tmp_path, web_storage):
    database = tmp_path / "unsupported.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('CREATE TABLE "user" (id INTEGER PRIMARY KEY, username TEXT)')
        connection.execute('INSERT INTO "user" VALUES (1, "preserve")')
        connection.commit()
    with pytest.raises(RuntimeError, match="Unsupported legacy user schema"):
        with TestClient(create_app(db_url=f"sqlite://{database}")):
            pass
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT * FROM "user"').fetchall() == [(1, "preserve")]
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='pnbp_schema_migrations'").fetchall() == []
    assert len(list((tmp_path / "migration-backups").glob("*.sqlite3"))) == 1


def test_backup_failure_prevents_schema_changes(tmp_path, web_storage, root_credentials, monkeypatch):
    database = tmp_path / "legacy.sqlite3"
    seed_legacy(database, root_credentials)
    before = legacy_rows(database)
    def failed_backup(*args):
        raise OSError("backup storage unavailable")
    monkeypatch.setattr(schema, "_backup", failed_backup)
    with pytest.raises(OSError, match="backup storage unavailable"):
        with TestClient(create_app(db_url=f"sqlite://{database}")):
            pass
    assert legacy_rows(database) == before


def test_backup_includes_committed_wal_rows(tmp_path, web_storage, root_credentials):
    database = tmp_path / "wal.sqlite3"
    seed_legacy(database, root_credentials)
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute('UPDATE "user" SET tok_uuid=? WHERE id=1', ["committed-wal-token"])
        writer.commit()
        with TestClient(create_app(db_url=f"sqlite://{database}")) as client:
            backup = client.app.state.schema_migration["backup_path"]
        assert legacy_rows(backup)["users"][0][3] == "committed-wal-token"


def test_migration_backup_symlink_is_refused(tmp_path, web_storage, root_credentials):
    database = tmp_path / "legacy.sqlite3"
    seed_legacy(database, root_credentials)
    (tmp_path / "outside").mkdir()
    (tmp_path / "migration-backups").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(RuntimeError, match="must not be a symlink"):
        with TestClient(create_app(db_url=f"sqlite://{database}")):
            pass
    assert list((tmp_path / "outside").iterdir()) == []


def test_non_sqlite_profile_requires_a_support_decision():
    with pytest.raises(RuntimeError, match="requires a SQLite"):
        create_app(db_url="postgres://localhost/unsupported")


def test_incomplete_current_history_is_not_accepted(tmp_path, web_storage):
    database = tmp_path / "history.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE pnbp_schema_migrations (version INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO pnbp_schema_migrations VALUES (1, 'base-schema')")
        connection.commit()
    with pytest.raises(RuntimeError, match="Invalid migration history schema"):
        with TestClient(create_app(db_url=f"sqlite://{database}")):
            pass


def test_partial_backup_failure_removes_incomplete_file(tmp_path, web_storage, root_credentials, monkeypatch):
    database = tmp_path / "legacy.sqlite3"
    seed_legacy(database, root_credentials)
    real_connect = schema.sqlite3.connect
    def fail_destination(path, *args, **kwargs):
        if isinstance(path, Path) and path.parent.name == "migration-backups":
            raise OSError("cannot open backup destination")
        return real_connect(path, *args, **kwargs)
    monkeypatch.setattr(schema.sqlite3, "connect", fail_destination)
    with pytest.raises(OSError, match="cannot open backup destination"):
        with TestClient(create_app(db_url=f"sqlite://{database}")):
            pass
    assert list((tmp_path / "migration-backups").iterdir()) == []
