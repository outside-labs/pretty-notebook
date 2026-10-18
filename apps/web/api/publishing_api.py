"""Negotiated, content-addressed publishing with checked writes."""

import asyncio
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import Field

from . import catalog, publish_api
from .atomic_io import atomic_write_bytes
from .permissions import require_permission
from .notebooks import publication_store, image_directory

router = APIRouter(prefix="/api/publishing", dependencies=[Depends(require_permission("publish"))])


class CheckedPublication(publish_api.PublicationInput):
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rendered_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    renderer_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def precondition(request, *, creating=True):
    match = request.headers.get("if-match")
    none = request.headers.get("if-none-match")
    if match is None and none is None:
        raise HTTPException(428, "Use the inventory ETag with If-Match, or If-None-Match: * to create.")
    if match is not None and none is not None:
        raise HTTPException(400, "Supply exactly one write precondition.")
    if none is not None:
        if not creating or none != "*":
            raise HTTPException(400, "Only If-None-Match: * is supported for creation.")
        return "*"
    if not match or not match.startswith('"') or not match.endswith('"') or "," in match or len(match) > 100:
        raise HTTPException(400, "Use one strong inventory ETag with If-Match.")
    return match


def image_etag(digest):
    return f'"sha256-{digest}"'


def image_digest(path):
    if path.is_symlink():
        raise HTTPException(400, "Images must be regular files.")
    with path.open("rb") as stream:
        data = stream.read(publish_api.MAX_IMAGE_BYTES + 1)
    if len(data) > publish_api.MAX_IMAGE_BYTES:
        raise HTTPException(413, "Stored image exceeds the 10 MiB limit.")
    return hashlib.sha256(data).hexdigest()


@router.get("/capabilities")
async def capabilities():
    return {"protocol": "revision-1", "content_hashes": True, "checked_publications": True,
            "checked_images": True, "legacy_mode": "0.9", "single_notebook": True, "independent_notebooks": True}


@router.get("/inventory")
async def inventory(request: Request):
    store = await publication_store(request)
    async with store.lock:
        pages = await store.inventory(detailed=True)
        images = []
        directory = await image_directory(request)
        for path in sorted(directory.iterdir()) if directory.exists() else ():
            if path.is_file() and path.suffix.lower() in publish_api.ALLOWED_IMAGE_EXTENSIONS:
                digest = await asyncio.to_thread(image_digest, path)
                images.append({"name": path.name, "source_hash": digest, "etag": image_etag(digest)})
    return {"notebook_id": store.notebook_id, "pages": pages, "images": images}


@router.put("/publication")
async def publish(request: Request, publication: CheckedPublication):
    expected = precondition(request)
    publish_api.publication_path(publication.name)
    digest = hashlib.sha256(publication.content.encode("utf-8")).hexdigest()
    if digest != publication.rendered_hash:
        raise HTTPException(400, "Rendered hash does not match the supplied HTML bytes.")
    try:
        note = await (await publication_store(request)).publish(
            publication.name, publication.content, title=publication.title,
            aliases=publication.aliases, previous_name=publication.previous_name,
            checked=True, expected_etag=expected, source_hash=publication.source_hash,
            renderer_fingerprint=publication.renderer_fingerprint,
        )
    except catalog.RevisionConflict as error:
        raise HTTPException(412, str(error)) from error
    except catalog.RouteConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return JSONResponse(
        {"name": publication.name, "revision": note["current_revision"],
         "etag": catalog.publication_etag(note), "rendered_hash": digest},
        status_code=201 if expected == "*" else 200,
        headers={"ETag": catalog.publication_etag(note)},
    )


@router.delete("/publication/{name:path}")
async def delete(request: Request, name: str):
    expected = precondition(request, creating=False)
    publish_api.publication_path(name)
    try:
        await (await publication_store(request)).delete(name, checked=True, expected_etag=expected)
    except catalog.RevisionConflict as error:
        raise HTTPException(412, str(error)) from error
    except catalog.RouteConflict as error:
        raise HTTPException(409, str(error)) from error
    return {"name": name, "deleted": True}


@router.put("/image")
async def image(request: Request, file: Annotated[UploadFile, File(...)]):
    expected = precondition(request)
    target, content = await publish_api.read_image_upload(file, directory=await image_directory(request))
    digest = hashlib.sha256(content).hexdigest()
    async with request.app.state.publications.lock:
        current = image_etag(await asyncio.to_thread(image_digest, target)) if target.exists() else None
        if (expected == "*" and current is not None) or (expected != "*" and expected != current):
            raise HTTPException(412, "Image changed; refresh the inventory before retrying.")
        await atomic_write_bytes(target, content)
    etag = image_etag(digest)
    return JSONResponse({"name": file.filename, "source_hash": digest, "etag": etag},
                        status_code=201 if expected == "*" else 200, headers={"ETag": etag})
