import json
from dataclasses import replace
from pathlib import Path
from stat import S_IMODE
from uuid import uuid4

import pytest
import requests
from cli_runner import CliRunner

from pretty_notebook import Notebook
from pretty_notebook._internal import publication_plan as plans, publication_state as state
from pretty_notebook.cli import cli

SERVER_ID = "a02a9862-f303-41b8-baa0-ef6c1eb04e3f"


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class CheckedRemote:
    def __init__(self, monkeypatch):
        self.pages, self.images, self.writes = {}, {}, []
        self.fail_name = self.lose_name = None
        self.before_put = None
        self.counter = 0
        for name in ("get", "post", "put", "delete"):
            monkeypatch.setattr(requests, name, getattr(self, name))

    def get(self, url, **kwargs):
        if url.endswith("/capabilities"):
            return Response({"protocol": "revision-1", "content_hashes": True, "checked_publications": True,
                             "checked_images": True, "single_notebook": True})
        assert url.endswith("/inventory")
        return Response({"notebook_id": SERVER_ID, "pages": list(self.pages.values()), "images": list(self.images.values())})

    def post(self, url, **kwargs):
        assert url.endswith("/api/routes/preview")
        return Response({"valid": True, "conflicts": []})

    def _matches(self, headers, current):
        if headers.get("If-None-Match") == "*":
            return current is None
        return current is not None and headers.get("If-Match") == current["etag"]

    def seed(self, name, data=None):
        data = data or {"name": name[:-5], "title": name, "aliases": [], "source_hash": "0" * 64,
                        "rendered_hash": "0" * 64, "renderer_fingerprint": "0" * 64}
        self.counter += 1
        old = self.pages.get(name)
        self.pages[name] = {"pub_name": name, "etag": f'"page-{self.counter}"',
            "id": old["id"] if old else str(uuid4()), "notebook_id": SERVER_ID,
            "revision": old["revision"] + 1 if old else 1,
            **{key: data[key] for key in ("title", "aliases", "source_hash", "rendered_hash", "renderer_fingerprint")}}
        return self.pages[name]

    def put(self, url, **kwargs):
        if self.before_put:
            callback, self.before_put = self.before_put, None
            callback()
        headers = kwargs["headers"]
        if url.endswith("/image"):
            name, data, _ = kwargs["files"]["file"]
            self.writes.append(("image", name, headers))
            if name == self.fail_name:
                return Response({}, 500)
            if not self._matches(headers, self.images.get(name)):
                return Response({}, 412)
            image_hash = plans.digest(data)
            record = {"name": name, "source_hash": image_hash, "etag": f'"sha256-{image_hash}"'}
            self.images[name] = record
            return Response(record, headers={"ETag": record["etag"]})
        data = kwargs["json"]
        name = data["name"] + ".html"
        self.writes.append(("page", name, headers))
        if name == self.fail_name:
            return Response({}, 500)
        if not self._matches(headers, self.pages.get(name)):
            return Response({}, 412)
        record = self.seed(name, data)
        if name == self.lose_name:
            self.lose_name = None
            raise requests.ConnectionError("response lost after successful commit")
        return Response({"name": data["name"], "revision": record["revision"], "etag": record["etag"],
                         "rendered_hash": record["rendered_hash"]}, headers={"ETag": record["etag"]})

    def delete(self, url, **kwargs):
        name = url.split("/publication/", 1)[1] + ".html"
        self.writes.append(("delete", name, kwargs["headers"]))
        if not self._matches(kwargs["headers"], self.pages.get(name)):
            return Response({}, 412)
        del self.pages[name]
        return Response({"name": name[:-5], "deleted": True})


@pytest.fixture
def local(tmp_path):
    root, images = tmp_path / "notes", tmp_path / "images"
    root.mkdir()
    images.mkdir()
    (root / "note.md").write_text("#public\nFirst")
    return Notebook(root, settings={"API_BASE": "https://publish.example", "IMG_PATH": str(images)}, settings_file="off")


@pytest.fixture
def remote(monkeypatch):
    return CheckedRemote(monkeypatch)


def receipt_path(local):
    return Path(local.NOTE_PATH) / ".pnbp" / "sync.json"


def test_checked_execution_persists_private_receipts_and_retries_skip_matching_content(local, remote):
    assert local.post_commits_to_web_api(stage_only=True)["dry_run"]
    assert remote.writes == [] and not receipt_path(local).exists()
    result = local.post_commits_to_web_api()
    assert result["pages"][0]["action"] == "create"
    saved = json.loads(receipt_path(local).read_text())["targets"][local.API_BASE]
    assert saved["pages"]["note.html"]["etag"] == remote.pages["note.html"]["etag"]
    assert S_IMODE(receipt_path(local).stat().st_mode) == 0o600
    count = len(remote.writes)
    assert local.post_commits_to_web_api()["pages"][0]["action"] == "unchanged"
    assert len(remote.writes) == count


@pytest.mark.parametrize("change", ["source", "target", "settings", "image", "content"])
def test_snapshot_binding_changes_stop_before_remote_mutation(local, remote, change):
    if change == "image":
        (Path(local.NOTE_PATH) / "note.md").write_text("#public\n![[photo.png]]")
        (Path(local.IMG_PATH) / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\nFirst")
    plan = local.prepare_publication()
    if change == "source":
        (Path(local.NOTE_PATH) / "note.md").write_text("#public\nChanged")
    elif change == "target":
        local.API_BASE = "https://other.example"
    elif change == "settings":
        local.config["HIDE_COMMIT_TAG"] = True
    elif change == "image":
        (Path(local.IMG_PATH) / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\nChanged")
    else:
        plan = replace(plan, pages=(replace(plan.pages[0], content="Forged"),))
    with pytest.raises(ValueError, match="no longer matches"):
        local.execute_publication(plan)
    assert remote.writes == [] and not receipt_path(local).exists()


def test_stale_remote_after_planning_and_during_put_cannot_overwrite(local, remote):
    local.post_commits_to_web_api()
    (Path(local.NOTE_PATH) / "note.md").write_text("#public\nLocal second")
    plan = local.prepare_publication()
    remote.seed("note.html")
    before = len(remote.writes)
    with pytest.raises(ValueError, match="Remote representation changed"):
        local.execute_publication(plan)
    assert len(remote.writes) == before
    reviewed = local.prepare_publication(accept_remote=True)
    remote.before_put = lambda: remote.seed("note.html")
    with pytest.raises(requests.HTTPError, match="412"):
        local.execute_publication(reviewed)


def test_remote_divergence_becomes_a_plan_conflict_until_explicitly_accepted(local, remote):
    local.post_commits_to_web_api()
    remote.seed("note.html")
    plan = local.prepare_publication()
    assert plan.pages[0].action == "conflict"
    before = len(remote.writes)
    with pytest.raises(ValueError, match="conflicts"):
        local.execute_publication(plan)
    assert len(remote.writes) == before
    assert local.prepare_publication(accept_remote=True).pages[0].action == "update"
    local.post_commits_to_web_api(accept_remote=True)
    assert local.prepare_publication().pages[0].action == "unchanged"


def test_partial_success_is_checkpointed_and_failure_stops_before_prune(local, remote):
    (Path(local.NOTE_PATH) / "second.md").write_text("#public\nSecond")
    remote.seed("stale.html")
    remote.fail_name = "second.html"
    with pytest.raises(requests.HTTPError, match="500"):
        local.post_commits_to_web_api(prune=True)
    saved = json.loads(receipt_path(local).read_text())["targets"][local.API_BASE]
    assert set(saved["pages"]) == {"note.html"}
    assert "stale.html" in remote.pages
    assert not any(kind == "delete" for kind, _, _ in remote.writes)
    remote.fail_name = None
    plan = local.prepare_publication(prune=True)
    assert plan.pages[0].action == "unchanged"
    local.execute_publication(plan)
    assert "stale.html" not in remote.pages
    assert sum(kind == "page" and name == "note.html" for kind, name, _ in remote.writes) == 1


def test_lost_success_response_is_recovered_by_authoritative_matching_inventory(local, remote):
    remote.lose_name = "note.html"
    with pytest.raises(requests.ConnectionError):
        local.post_commits_to_web_api()
    assert not receipt_path(local).exists()
    plan = local.prepare_publication()
    assert plan.pages[0].action == "unchanged"
    local.execute_publication(plan)
    assert remote.pages["note.html"]["revision"] == 1 and receipt_path(local).exists()


def test_failed_atomic_receipt_write_keeps_previous_checkpoint_and_is_recoverable(local, remote, monkeypatch):
    local.post_commits_to_web_api()
    before = receipt_path(local).read_bytes()
    (Path(local.NOTE_PATH) / "note.md").write_text("#public\nSecond")
    def fail_replace(*args):
        raise OSError("receipt disk full")
    with monkeypatch.context() as patch:
        patch.setattr(state.os, "replace", fail_replace)
        with pytest.raises(OSError, match="disk full"):
            local.post_commits_to_web_api(prune=True)
    assert receipt_path(local).read_bytes() == before
    assert not list(receipt_path(local).parent.glob(".sync-*.tmp"))
    assert not (receipt_path(local).parent / "sync.lock").exists()
    assert local.prepare_publication().pages[0].action == "unchanged"
    local.post_commits_to_web_api()
    assert receipt_path(local).read_bytes() != before


def test_source_edit_during_uploads_stops_before_prune(local, remote):
    remote.seed("stale.html")
    remote.before_put = lambda: (Path(local.NOTE_PATH) / "note.md").write_text("#public\nExternal edit")
    with pytest.raises(ValueError, match="snapshot"):
        local.post_commits_to_web_api(prune=True)
    assert "stale.html" in remote.pages
    assert not any(kind == "delete" for kind, _, _ in remote.writes)


def test_image_failure_stops_before_page_uploads_and_prune(local, remote):
    (Path(local.NOTE_PATH) / "note.md").write_text("#public\n![[photo.png]]")
    (Path(local.IMG_PATH) / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\nFirst")
    remote.seed("stale.html")
    remote.fail_name = "photo.png"
    with pytest.raises(requests.HTTPError):
        local.post_commits_to_web_api(prune=True)
    assert all(kind == "image" for kind, _, _ in remote.writes)
    assert not receipt_path(local).exists()


def test_changed_corrupt_or_symlinked_receipts_fail_before_remote_writes(local, remote, tmp_path):
    plan = local.prepare_publication()
    receipt_path(local).parent.mkdir()
    receipt_path(local).write_text('{"version":1,"targets":{}}')
    with pytest.raises(ValueError, match="Sync receipts changed"):
        local.execute_publication(plan)
    receipt_path(local).write_text("not json")
    with pytest.raises(ValueError, match="Unreadable"):
        local.prepare_publication()
    receipt_path(local).unlink()
    outside = tmp_path / "outside.json"
    outside.write_text('{"version":1,"targets":{}}')
    receipt_path(local).symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks"):
        local.prepare_publication()
    assert remote.writes == []


def test_checked_cli_preview_and_execution_report_conflicts_with_nonzero_exit(local, remote, monkeypatch):
    monkeypatch.setenv("NOTE_PATH", local.NOTE_PATH)
    monkeypatch.setenv("API_BASE", local.API_BASE)
    monkeypatch.setenv("PNBP_SETTINGS", "off")
    preview = CliRunner().invoke(cli, ["commit-stage", "--json", "--mode", "checked", "--prune"])
    assert preview.exit_code == 0 and json.loads(preview.output)["mode"] == "revision-1"
    assert not receipt_path(local).exists()
    assert CliRunner().invoke(cli, ["commit-remote", "--mode", "checked"]).exit_code == 0
    remote.seed("note.html")
    failed = CliRunner().invoke(cli, ["commit-remote", "--mode", "checked"])
    assert failed.exit_code == 1 and "conflicts" in failed.output


def test_forged_prune_action_cannot_delete_a_current_local_publication(local, remote):
    local.post_commits_to_web_api()
    plan = local.prepare_publication(prune=True)
    forged = replace(plan, pages=(replace(plan.pages[0], action="delete"),))
    before = len(remote.writes)
    with pytest.raises(ValueError, match="invalid actions"):
        local.execute_publication(forged)
    assert len(remote.writes) == before and "note.html" in remote.pages


def test_invalid_success_receipt_stops_before_prune_and_inventory_recovers(local, remote, monkeypatch):
    remote.seed("stale.html")
    original = requests.put
    def invalid_receipt(*args, **kwargs):
        response = original(*args, **kwargs)
        response.headers["ETag"] = '"unexpected"'
        return response
    with monkeypatch.context() as patch:
        patch.setattr(requests, "put", invalid_receipt)
        with pytest.raises(ValueError, match="Invalid checked publication receipt"):
            local.post_commits_to_web_api(prune=True)
    assert "stale.html" in remote.pages and not receipt_path(local).exists()
    assert local.prepare_publication().pages[0].action == "unchanged"
