from pretty_notebook._internal.web_state import CURRENT_VERSION
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from functools import partial
from stat import S_IMODE
from uuid import UUID

import pytest
from api import catalog, schema
from fastapi.testclient import TestClient
from main import create_app
from tortoise import connections


def call(client, method, *args, **kwargs):
    return client.portal.call(partial(getattr(client.app.state.publications, method), *args, **kwargs))


def rows(client, statement, values=None):
    async def query():
        return await connections.get("default").execute_query_dict(statement, values)
    return client.portal.call(query)


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def test_catalog_revisions_keep_unknown_source_and_actual_rendered_features(client, web_storage):
    first = "<div class='mermaid'>graph TD; A-->B</div><pre><code>one</code></pre>"
    call(client, "publish", "note", first)
    note, = rows(client, "SELECT * FROM pnbp_notes")
    revision, = rows(client, "SELECT * FROM pnbp_revisions")
    assert str(UUID(note["id"])) == note["id"]
    assert note["notebook_id"] == client.app.state.publications.notebook_id
    assert note["canonical_route"] == "/note"
    assert json.loads(note["aliases"]) == []
    assert revision["source_hash"] is None
    assert revision["renderer_fingerprint"] is None
    assert revision["rendered_hash"] == revision["body_hash"] == digest(first)
    assert json.loads(revision["feature_flags"]) == ["code", "mermaid"]
    original_blob = web_storage.pages / ".blobs" / f"{digest(first)}.html"
    assert original_blob.read_bytes() == first.encode()
    assert S_IMODE(original_blob.stat().st_mode) == 0o600
    call(client, "publish", "note", "<table><tr><td>second</td></tr></table>")
    assert "second" in client.get("/note").text
    assert rows(client, "SELECT current_revision FROM pnbp_notes")[0]["current_revision"] == 2
    assert len(rows(client, "SELECT * FROM pnbp_revisions")) == 2
    assert original_blob.read_bytes() == first.encode()


def test_legacy_import_preserves_literal_bodies_times_and_distinct_ids(tmp_path, web_storage):
    source = "<p>{{ 7 * 7 }}</p>\r\n{% set never_run = true %}"
    envelope = catalog.LEGACY_PAGE_PREFIX.replace("\n", "\r\n") + source + catalog.LEGACY_PAGE_SUFFIX.replace("\n", "\r\n")
    for name in ("one", "two"):
        path = web_storage.pages / f"{name}.html"
        path.write_bytes(envelope.encode())
        os.utime(path, (1_600_000_000, 1_600_000_000))
    database = tmp_path / "site.sqlite3"
    with TestClient(create_app(db_url=f"sqlite://{database}")) as client:
        notes = rows(client, "SELECT * FROM pnbp_notes ORDER BY canonical_route")
        notebook_id = client.app.state.publications.notebook_id
        assert notes[0]["id"] != notes[1]["id"]
        assert {note["notebook_id"] for note in notes} == {notebook_id}
        assert call(client, "read", "one") == source
        assert source in client.get("/one").text
        assert "<p>49</p>" not in client.get("/one").text
        assert call(client, "inventory")[0]["mod_date"] == datetime.fromtimestamp(1_600_000_000, UTC).isoformat()
        assert len(list((web_storage.pages / ".blobs").glob("*.html"))) == 1
    with TestClient(create_app(db_url=f"sqlite://{database}")) as restarted:
        assert restarted.app.state.publications.notebook_id == notebook_id
        assert rows(restarted, "SELECT * FROM pnbp_notes ORDER BY canonical_route") == notes
    assert (web_storage.pages / "one.html").read_bytes() == envelope.encode()


def test_failed_blob_write_preserves_current_revision(client, monkeypatch):
    call(client, "publish", "note", "Original head")
    before = rows(client, "SELECT * FROM pnbp_notes")
    def fail_write(*args):
        raise OSError("body storage unavailable")
    monkeypatch.setattr(catalog, "_write_blob", fail_write)
    with pytest.raises(OSError, match="body storage unavailable"):
        call(client, "publish", "note", "Uncommitted body")
    assert rows(client, "SELECT * FROM pnbp_notes") == before
    assert "Original head" in client.get("/note").text


def test_failed_revision_transaction_keeps_head_and_produces_collectable_orphan(client, monkeypatch, web_storage):
    call(client, "publish", "note", "Original head")
    original_revision = catalog.PublicationStore._revision
    async def fail_after_insert(self, transaction, *args):
        await original_revision(self, transaction, *args)
        raise OSError("catalog transaction failed")
    monkeypatch.setattr(catalog.PublicationStore, "_revision", fail_after_insert)
    with pytest.raises(OSError, match="catalog transaction failed"):
        call(client, "publish", "note", "Uncommitted body")
    assert len(rows(client, "SELECT * FROM pnbp_revisions")) == 1
    assert "Original head" in client.get("/note").text
    orphan = web_storage.pages / ".blobs" / f"{digest('Uncommitted body')}.html"
    assert orphan.read_text() == "Uncommitted body"
    plan = call(client, "collect_orphans")
    assert plan["dry_run"] is True and plan["orphans"] == [orphan.stem]
    assert orphan.exists()
    call(client, "collect_orphans", dry_run=False)
    assert not orphan.exists()
    assert "Original head" in client.get("/note").text


def test_restart_after_blob_before_catalog_commit_keeps_previous_head(tmp_path, web_storage, monkeypatch):
    database = tmp_path / "site.sqlite3"
    with TestClient(create_app(db_url=f"sqlite://{database}")) as client:
        call(client, "publish", "note", "Original head")
        with monkeypatch.context() as patch:
            async def stopped(*args):
                raise OSError("process stopped before catalog commit")
            patch.setattr(client.app.state.publications, "_commit_publication", stopped)
            with pytest.raises(OSError):
                call(client, "publish", "note", "New complete orphan")
    with TestClient(create_app(db_url=f"sqlite://{database}")) as restarted:
        assert "Original head" in restarted.get("/note").text
        assert len(rows(restarted, "SELECT * FROM pnbp_revisions")) == 1
        assert call(restarted, "collect_orphans")["orphans"] == [digest("New complete orphan")]


def test_deleted_and_historical_revisions_are_never_collected(client, web_storage):
    call(client, "publish", "note", "Version one")
    call(client, "publish", "note", "Version two")
    assert call(client, "delete", "note") is True
    assert call(client, "delete", "note") is False
    assert client.get("/note").status_code == 404
    assert call(client, "inventory") == []
    assert call(client, "collect_orphans", dry_run=False)["count"] == 0
    assert len(list((web_storage.pages / ".blobs").glob("*.html"))) == 2
    note_id = rows(client, "SELECT id FROM pnbp_notes")[0]["id"]
    call(client, "publish", "note", "Version three")
    restored = rows(client, "SELECT * FROM pnbp_notes")[0]
    assert restored["id"] == note_id and restored["current_revision"] == 3
    assert "Version three" in client.get("/note").text


def test_external_legacy_file_is_read_only_until_imported_and_delete_keeps_original(client, web_storage):
    path = web_storage.pages / "external.html"
    path.write_text("External legacy body")
    assert "External legacy body" in client.get("/external").text
    assert rows(client, "SELECT * FROM pnbp_notes") == []
    assert call(client, "delete", "external") is True
    assert path.read_text() == "External legacy body"
    assert client.get("/external").status_code == 404
    assert call(client, "collect_orphans")["count"] == 0


def test_version_one_database_upgrades_with_backup_and_legacy_import(tmp_path, web_storage):
    database = tmp_path / "version-one.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        for statement in schema.BASE_SCHEMA:
            connection.execute(statement)
        connection.execute(schema.HISTORY_SCHEMA)
        connection.execute("INSERT INTO pnbp_schema_migrations (version, name, applied_at) VALUES (1, 'base-schema', '2026-10-01')")
        connection.commit()
    (web_storage.pages / "legacy.html").write_text("Legacy survives")
    with TestClient(create_app(db_url=f"sqlite://{database}")) as client:
        report = client.app.state.schema_migration
        assert report["version"] == CURRENT_VERSION and report["backup_path"]
        assert "Legacy survives" in client.get("/legacy").text
        assert [row["version"] for row in rows(client, "SELECT version FROM pnbp_schema_migrations ORDER BY version")] == list(range(1, CURRENT_VERSION + 1))
    with closing(sqlite3.connect(report["backup_path"])) as backup:
        assert backup.execute("SELECT version FROM pnbp_schema_migrations").fetchall() == [(1,)]


def test_body_corruption_and_symlinks_fail_closed(client, web_storage, tmp_path):
    call(client, "publish", "note", "Original head")
    path = web_storage.pages / ".blobs" / f"{digest('Original head')}.html"
    path.write_text("Corrupted data")
    assert client.get("/note").status_code == 500
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        call(client, "publish", "second", "Original head")
    path.unlink()
    outside = tmp_path / "outside.html"
    outside.write_text("Original head")
    path.symlink_to(outside)
    assert client.get("/note").status_code == 500
    assert outside.read_text() == "Original head"


def test_orphan_plan_is_bounded_and_does_not_remove_unmanaged_files(client, web_storage):
    for body in ("Orphan one", "Orphan two"):
        catalog._write_blob(client.app.state.publications.blobs, body)
    unmanaged = web_storage.pages / ".blobs" / "README.txt"
    unmanaged.write_text("Keep")
    preview = call(client, "collect_orphans", limit=1)
    assert preview["count"] == 2 and preview["truncated"] is True
    assert len(preview["orphans"]) == 1
    call(client, "collect_orphans", dry_run=False, limit=1)
    assert call(client, "collect_orphans")["count"] == 1
    assert unmanaged.read_text() == "Keep"
    with pytest.raises(ValueError, match="limit"):
        call(client, "collect_orphans", limit=0)


def test_invalid_catalog_hash_cannot_escape_blob_directory(client, web_storage):
    call(client, "publish", "note", "Original head")
    rows(client, "UPDATE pnbp_revisions SET body_hash='../outside' WHERE revision=1")
    assert client.get("/note").status_code == 500
    assert len(list((web_storage.pages / ".blobs").glob("*.html"))) == 1


def test_partial_blob_link_failure_keeps_old_head_and_cleans_temp(client, web_storage, monkeypatch):
    call(client, "publish", "note", "Original head")
    def failed_link(*args):
        raise OSError("cannot install new blob")
    monkeypatch.setattr(catalog.os, "link", failed_link)
    with pytest.raises(OSError, match="cannot install new blob"):
        call(client, "publish", "note", "New body")
    assert list((web_storage.pages / ".blobs").glob(".body-*.tmp")) == []
    assert "Original head" in client.get("/note").text


def test_legacy_import_is_transactional_and_retry_preserves_originals(tmp_path, web_storage, monkeypatch):
    database = tmp_path / "site.sqlite3"
    (web_storage.pages / "one.html").write_text("One")
    (web_storage.pages / "two.html").write_text("Two")
    real_create = catalog.PublicationStore._create
    async def fail_second(self, transaction, name, *args, **kwargs):
        result = await real_create(self, transaction, name, *args, **kwargs)
        if name == "two":
            raise OSError("second import failed")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(catalog.PublicationStore, "_create", fail_second)
        with pytest.raises(OSError, match="second import failed"):
            with TestClient(create_app(db_url=f"sqlite://{database}")):
                pass
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT * FROM pnbp_notes").fetchall() == []
    assert (web_storage.pages / "one.html").read_text() == "One"
    assert (web_storage.pages / "two.html").read_text() == "Two"
    with TestClient(create_app(db_url=f"sqlite://{database}")) as restarted:
        assert "One" in restarted.get("/one").text
        assert len(rows(restarted, "SELECT * FROM pnbp_notes")) == 2


def test_legacy_tombstone_survives_restart_without_resurrecting_original(tmp_path, web_storage):
    database = tmp_path / "site.sqlite3"
    (web_storage.pages / "legacy.html").write_text("Kept original")
    with TestClient(create_app(db_url=f"sqlite://{database}")) as client:
        assert call(client, "delete", "legacy") is True
    with TestClient(create_app(db_url=f"sqlite://{database}")) as restarted:
        assert restarted.get("/legacy").status_code == 404
        assert call(restarted, "inventory") == []
        assert call(restarted, "collect_orphans")["count"] == 0
    assert (web_storage.pages / "legacy.html").read_text() == "Kept original"


def test_republishing_external_legacy_file_records_original_history(client, web_storage):
    path = web_storage.pages / "legacy.html"
    path.write_text("Original externally added file")
    call(client, "publish", "legacy", "Catalog replacement")
    assert path.read_text() == "Original externally added file"
    assert "Catalog replacement" in client.get("/legacy").text
    revisions = rows(client, "SELECT * FROM pnbp_revisions ORDER BY revision")
    assert [row["body_hash"] for row in revisions] == [digest("Original externally added file"), digest("Catalog replacement")]
