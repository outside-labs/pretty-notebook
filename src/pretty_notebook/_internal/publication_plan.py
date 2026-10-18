"""Read-only, immutable publication plans bound to exact local snapshots."""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import requests

from pretty_notebook._internal import rendering as _rendering, routes as _routes

DIGEST = re.compile(r"[a-f0-9]{64}\Z")
ETAG = re.compile(r'"[A-Za-z0-9:_-]{1,96}"\Z')
MAX_RECORDS = 10_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def api_target(notebook):
    target = notebook.API_BASE
    try:
        parsed = urlsplit(target)
        valid = (isinstance(target, str) and parsed.scheme in {"http", "https"}
                 and parsed.hostname and parsed.port != 0 and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and not any(ord(char) <= 32 for char in target) and "\\" not in target)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Publishing requires an HTTP(S) API_BASE without credentials, query, or fragment.")
    return target.rstrip("/")


def negotiate(notebook, mode="auto"):
    if mode not in {"auto", "checked", "legacy"}:
        raise ValueError("Publication mode must be auto, checked, or legacy.")
    api_target(notebook)
    if mode == "legacy":
        return False
    try:
        response = notebook._api_request(requests.get, "/api/publishing/capabilities", headers=notebook.get_headers())
    except requests.HTTPError as error:
        if mode == "auto" and error.response is not None and error.response.status_code == 404:
            return False
        raise
    capabilities = response.json()
    if not isinstance(capabilities, dict) or capabilities.get("protocol") != "revision-1" or any(
        capabilities.get(key) is not True for key in ("content_hashes", "checked_publications", "checked_images", "single_notebook")
    ):
        raise ValueError("The server does not advertise the supported checked publishing contract.")
    return True


def renderer_fingerprint(notebook):
    settings = {key: notebook.config.get(key) for key in (
        "MARKDOWN_BACKEND", "HIDE_COMMIT_TAG", "URL_PREFIX", "ROUTE_MODE", "NOTEBOOK_SLUG", "SERVER_NOTEBOOK", "PUBLICATION_ROUTES",
    )}
    settings.update(PUB_LNK_ONLY=notebook.PUB_LNK_ONLY, COMMIT_TAG=notebook.COMMIT_TAG, EXCLUDE_TAG=notebook.EXCLUDE_TAG)
    value = {"policy": "revision-2", "pnbp": version("pretty-notebook"),
             "renderer": _rendering.backend_identity(notebook), "settings": settings}
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def source_snapshot(notebook):
    root = Path(notebook.NOTE_PATH).resolve()
    sources = []
    for note in notebook.notes.values():
        path = (root / note.source_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Publication source escapes the notebook.")
        data = path.read_bytes()
        if data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n") != note.md:
            raise ValueError("A source changed during publication planning; reload and retry.")
        sources.append((note.source_path, digest(data)))
    metadata = root / ".pnbp" / "metadata.json"
    if metadata.parent.is_symlink() or metadata.is_symlink():
        raise ValueError("Publication state must not use symlinks.")
    return tuple(sorted(sources)), digest(metadata.read_bytes()) if metadata.exists() else None


@dataclass(frozen=True)
class PageAction:
    name: str
    action: str
    expected_etag: str | None = None
    source_path: str | None = None
    source_hash: str | None = None
    rendered_hash: str | None = None
    renderer_fingerprint: str | None = None
    title: str | None = None
    aliases: tuple[str, ...] = ()
    detail: str | None = None
    content: str | None = field(default=None, repr=False)

    def preview(self):
        return {key: getattr(self, key) for key in (
            "name", "action", "expected_etag", "source_path", "source_hash", "rendered_hash", "detail",
        )}


@dataclass(frozen=True)
class ImageAction:
    name: str
    action: str
    source_hash: str
    expected_etag: str | None
    path: Path = field(repr=False)
    content_type: str
    content: bytes = field(repr=False)
    detail: str | None = None

    def preview(self):
        return {key: getattr(self, key) for key in ("name", "action", "source_hash", "expected_etag", "detail")}


@dataclass(frozen=True)
class PublicationPlan:
    root: str
    notebook_id: str | None
    identity_hash: str | None
    target: str
    server_notebook_id: str
    fingerprint: str
    sources: tuple[tuple[str, str], ...]
    pages: tuple[PageAction, ...]
    images: tuple[ImageAction, ...]
    prune: bool
    checkpoint_hash: str | None = None

    def preview(self, limit=200):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Publication plan limit must be 1-200.")
        return {"mode": "revision-1", "dry_run": True, "prune": self.prune,
                "target": self.target, "notebook_id": self.notebook_id,
                "server_notebook_id": self.server_notebook_id, "renderer_fingerprint": self.fingerprint,
                "pages": [page.preview() for page in self.pages[:limit]],
                "images": [image.preview() for image in self.images[:limit]],
                "page_count": len(self.pages), "image_count": len(self.images),
                "truncated": len(self.pages) > limit or len(self.images) > limit}


def _uuid(value):
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def read_inventory(notebook):
    data = notebook._api_request(requests.get, "/api/publishing/inventory", headers=notebook.get_headers()).json()
    if not isinstance(data, dict) or not _uuid(data.get("notebook_id")):
        raise ValueError("Invalid checked publishing inventory.")
    result = {}
    for key, name_key in (("pages", "pub_name"), ("images", "name")):
        records = data.get(key)
        if not isinstance(records, list) or len(records) > MAX_RECORDS:
            raise ValueError("Invalid or oversized checked publishing inventory.")
        by_name = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get(name_key), str):
                raise ValueError("Invalid checked publishing inventory record.")
            name = record[name_key]
            if name in by_name:
                raise ValueError("Duplicate checked publishing inventory name.")
            if key == "pages":
                if not name.endswith(".html"):
                    raise ValueError("Invalid publication inventory filename.")
                _routes.validate_route("/" + name[:-5], allow_namespace=True)
            elif Path(name).name != name or Path(name).suffix.lower() not in notebook.PUBLICATION_IMAGE_EXTENSIONS:
                raise ValueError("Invalid image inventory filename.")
            if key == "pages" and record.get("etag") is None:
                by_name[name] = record
                continue
            if not isinstance(record.get("etag"), str) or not ETAG.fullmatch(record["etag"]):
                raise ValueError("Checked inventory requires a strong ETag.")
            hash_keys = ("source_hash", "rendered_hash", "renderer_fingerprint") if key == "pages" else ("source_hash",)
            for hash_key in hash_keys:
                value = record.get(hash_key)
                if value is None and key == "pages" and hash_key != "rendered_hash":
                    continue
                if not isinstance(value, str) or not DIGEST.fullmatch(value):
                    raise ValueError("Invalid checked inventory digest.")
            if key == "pages":
                if (type(record.get("revision")) is not int or record["revision"] < 1
                    or not _uuid(record.get("id")) or record.get("notebook_id") != data["notebook_id"]
                    or not isinstance(record.get("title"), str) or not isinstance(record.get("aliases"), list)):
                    raise ValueError("Invalid checked publication metadata.")
                for alias in record["aliases"]:
                    _routes.validate_route(alias, allow_namespace=True)
            elif record["etag"] != f'"sha256-{record["source_hash"]}"':
                raise ValueError("Image ETag does not match its digest.")
            by_name[name] = record
        result[key] = by_name
    return data["notebook_id"], result["pages"], result["images"]


def _route_conflicts(notebook, entries):
    conflicts = {}
    for start in range(0, len(entries), 200):
        claims = [{"name": entry["route"][1:], "aliases": entry["aliases"]} for entry in entries[start:start + 200]]
        result = notebook._api_request(requests.post, "/api/routes/preview", json=claims, headers=notebook.get_headers()).json()
        if not isinstance(result, dict) or type(result.get("valid")) is not bool or not isinstance(result.get("conflicts"), list):
            raise ValueError("Invalid read-only route preview.")
        names = {claim["name"] for claim in claims}
        for conflict in result["conflicts"]:
            if not isinstance(conflict, dict) or conflict.get("name") not in names or not isinstance(conflict.get("detail"), str):
                raise ValueError("Invalid route conflict diagnostic.")
            conflicts[conflict["name"] + ".html"] = "Remote route or alias collision; review the route preview."
        if result["valid"] != (not result["conflicts"]):
            raise ValueError("Inconsistent read-only route preview.")
    return conflicts


def _image_bytes(path):
    with path.open("rb") as stream:
        data = stream.read(10 * 1024 * 1024 + 1)
    suffix = path.suffix.lower()
    signatures = {".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
                  ".jpg": data.startswith(b"\xff\xd8\xff"), ".jpeg": data.startswith(b"\xff\xd8\xff"),
                  ".gif": data.startswith((b"GIF87a", b"GIF89a")),
                  ".webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP"}
    if len(data) > 10 * 1024 * 1024 or not signatures.get(suffix):
        raise ValueError("Checked publishing requires valid images of at most 10 MiB.")
    return data


def prepare(notebook, *, mode="auto", prune=False, refresh_images=False, accept_remote=False):
    from pretty_notebook._internal import publication_state as state
    if any(type(flag) is not bool for flag in (prune, refresh_images, accept_remote)):
        raise ValueError("Publication control flags must be booleans.")
    notebook._require_clean_notes("plan remote publishing")
    notebook.open_md()
    notes, images = notebook._publication_preflight(include_images=True)
    if not negotiate(notebook, mode):
        return None
    sources, identity_hash = source_snapshot(notebook)
    source_hashes = dict(sources)
    fingerprint = renderer_fingerprint(notebook)
    checkpoints, checkpoint_hash = state.read(notebook.NOTE_PATH)
    entries = notebook.publication_routes()["routes"]
    routes = {entry["source_path"]: entry for entry in entries}
    server_id, remote, remote_images = read_inventory(notebook)
    conflicts = _route_conflicts(notebook, entries)
    pages = []
    local_names = set()
    for note in notes:
        entry = routes[note.source_path]
        name = entry["route"][1:] + ".html"
        local_names.add(name)
        content = notebook.convert_to_html(note)
        if len(content) > 2_000_000:
            raise ValueError("Rendered publication exceeds the server's 2,000,000 character limit.")
        rendered_hash = digest(content.encode("utf-8"))
        current = remote.get(name)
        reason = conflicts.get(name)
        if current and current.get("etag") is None:
            reason = "Legacy publication needs catalog import before checked publishing."
        unchanged = current and all(current.get(key) == value for key, value in (
            ("source_hash", source_hashes[note.source_path]), ("rendered_hash", rendered_hash),
            ("renderer_fingerprint", fingerprint), ("title", entry["title"]),
        )) and set(entry["aliases"]) <= set(current.get("aliases", []))
        action = "conflict" if reason else "create" if current is None else "unchanged" if unchanged else "update"
        aliases = tuple(sorted(set(entry["aliases"]) | set(current.get("aliases", [])))) if current else tuple(entry["aliases"])
        pages.append(PageAction(name, action, current.get("etag") if current else None, note.source_path,
                                source_hashes[note.source_path], rendered_hash, fingerprint, entry["title"], aliases, reason, content))
    for name in sorted(set(remote) - local_names):
        etag = remote[name].get("etag")
        action = "conflict" if prune and etag is None else "delete" if prune else "preserve"
        pages.append(PageAction(name, action, etag, detail="Legacy publication needs catalog import." if action == "conflict" else None))
    image_actions = []
    for name, (path, content_type) in sorted(images.items()):
        data = _image_bytes(path)
        image_hash = digest(data)
        current = remote_images.get(name)
        action = "create" if current is None else "unchanged" if current["source_hash"] == image_hash and not refresh_images else "update"
        image_actions.append(ImageAction(name, action, image_hash, current["etag"] if current else None, path, content_type, data))
    if source_snapshot(notebook) != (sources, identity_hash):
        raise ValueError("Notebook changed during publication planning; reload and retry.")
    plan = PublicationPlan(str(Path(notebook.NOTE_PATH).resolve()), notebook.notebook_id, identity_hash,
                           api_target(notebook), server_id, fingerprint, sources, tuple(pages), tuple(image_actions), prune, checkpoint_hash)
    saved = state.binding(checkpoints, plan)
    if saved and not accept_remote:
        pages = [replace(page, action="conflict", detail="Remote page changed since its last successful receipt; review before accepting remote changes.")
                 if page.action not in {"preserve", "unchanged", "conflict"} and page.name in saved["pages"]
                 and page.expected_etag != saved["pages"][page.name]["etag"] else page for page in pages]
        image_actions = [replace(image, action="conflict", detail="Remote image changed since its last successful receipt; review before accepting remote changes.")
                         if image.action != "unchanged" and image.name in saved["images"]
                         and image.expected_etag != saved["images"][image.name]["etag"] else image for image in image_actions]
        plan = replace(plan, pages=tuple(pages), images=tuple(image_actions))
    return plan
