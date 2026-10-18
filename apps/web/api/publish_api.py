import datetime
from pathlib import Path
from typing import Annotated

import fastapi
from fastapi import Depends, File, HTTPException, UploadFile, Request
from pydantic import BaseModel, Field
from web_config import IMAGES_PATH, PAGES_PATH

from .atomic_io import atomic_write_bytes
from .permissions import require_permission
from .notebooks import publication_store, image_directory
from pretty_notebook._internal.routes import validate_route
from .catalog import RouteConflict
from .catalog import publication_body as publication_body
from .catalog import LEGACY_PAGE_PREFIX as LEGACY_PAGE_PREFIX, LEGACY_PAGE_SUFFIX as LEGACY_PAGE_SUFFIX

router = fastapi.APIRouter()

PUB_PATH = PAGES_PATH
MAX_PUBLICATION_CHARS = 2_000_000

IMG_PATH = IMAGES_PATH
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_SIGNATURES = {
    ".png": lambda content: content.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda content: content.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda content: content.startswith(b"\xff\xd8\xff"),
    ".gif": lambda content: content.startswith((b"GIF87a", b"GIF89a")),
    ".webp": lambda content: (
        len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    ),
}

class Publishment(BaseModel):
    name: str = Field(max_length=499)
    content: str = Field(max_length=MAX_PUBLICATION_CHARS)


class RouteClaim(BaseModel):
    name: str = Field(max_length=499)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    previous_name: str | None = Field(default=None, max_length=499)


class PublicationInput(Publishment, RouteClaim):
    title: str | None = Field(default=None, max_length=500)


def publication_path(name: str) -> Path:
    """build path to publishment, ensuring validity of slug-name"""
    try:
        validate_route("/" + name, allow_namespace=True)
    except ValueError as error:
        raise HTTPException(400, "Invalid publication name.") from error

    target = (PUB_PATH / f"{name}.html").resolve()

    if not target.is_relative_to(PUB_PATH):
        raise HTTPException(400, "Invalid publication path.")

    return target


async def add_publishment(name: str, content: str, *, store, **metadata) -> Publishment:
    """Store owner-authored HTML as data, never as executable Jinja source."""
    publication_path(name)
    try:
        await store.publish(name, content, **metadata)
    except RouteConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    pub = Publishment(
        name=name,
        content=content,
    )

    return pub


@router.post(
    "/api/publishment",
    name="add_pub",
    status_code=201,
    response_model=Publishment,
    dependencies=[Depends(require_permission("publish"))],
)  # if ok status_code 200 -> 201, if not, it's handled in the ValidationError
async def publishment_post(pub_submittal: PublicationInput, request: Request):
    """Store a publication."""
    n = pub_submittal.name
    c = pub_submittal.content

    return await add_publishment(n, c, store=await publication_store(request), title=pub_submittal.title, aliases=pub_submittal.aliases, previous_name=pub_submittal.previous_name)


@router.post("/api/routes/preview", dependencies=[Depends(require_permission("publish"))])
async def routes_preview(request: Request, claims: Annotated[list[RouteClaim], fastapi.Body(max_length=200)]):
    return await (await publication_store(request)).preview_routes([claim.model_dump() for claim in claims])


def image_path(filename: str | None, directory=None) -> Path:
    directory = IMG_PATH if directory is None else directory
    """ensures valid filename and file type of images"""
    if not filename:
        raise HTTPException(400, "Missing filename.")

    supplied = Path(filename)

    if supplied.name != filename:
        raise HTTPException(400, "Invalid filename.")

    if supplied.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(400, "Unsupported image type.")

    if (directory / supplied.name).is_symlink():
        raise HTTPException(400, "Images must be regular files.")
    target = (directory / supplied.name).resolve()

    if target.parent != directory:
        raise HTTPException(400, "Invalid image path.")

    return target


@router.post(
    "/api/image",
    name="add_img",
    status_code=201,
    dependencies=[Depends(require_permission("publish"))],
)
async def image_post(request: Request, file: Annotated[UploadFile, File(...)]):
    """Validate and atomically store a bounded image upload."""
    target, content = await read_image_upload(file, directory=await image_directory(request))
    async with request.app.state.publications.lock:
        await atomic_write_bytes(target, content)
    return {"filename": file.filename}


async def read_image_upload(file, *, directory=None):
    target = image_path(file.filename, directory)
    content = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()

    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds the 10 MiB limit.")

    suffix = target.suffix.lower()
    if not IMAGE_SIGNATURES[suffix](content):
        raise HTTPException(400, "File content does not match its image type.")

    return target, content


@router.get("/api/publishments", dependencies=[Depends(require_permission("publish"))])
async def publishments_get(request: Request) -> list:
    """Publishments Get"""
    return await (await publication_store(request)).inventory()


@router.get("/api/images", dependencies=[Depends(require_permission("publish"))])
async def images_get(request: Request) -> list:
    """Images Get"""
    directory = await image_directory(request)
    img_names = sorted(directory.iterdir(), key=lambda path: path.name) if directory.exists() else []
    img_data = []
    for i in img_names:
        if i.is_file() and i.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
            mod_date = datetime.datetime.fromtimestamp(
                i.stat().st_mtime,
                tz=datetime.UTC,
            )
            img_data.append({"img_name": i.name, "mod_date": mod_date})

    return img_data


@router.delete("/api/publishment/{pub_name:path}", dependencies=[Depends(require_permission("publish"))])
async def publishment_delete(pub_name: str, request: Request):
    """Publishment Delete"""
    supplied = Path(pub_name)

    if supplied.suffix != ".html":
        raise HTTPException(400, "Invalid publication filename.")

    name = pub_name[:-5]
    publication_path(name)

    try:
        if not await (await publication_store(request)).delete(name):
            raise HTTPException(404, "Publication not found.")
    except RouteConflict as error:
        raise HTTPException(409, str(error)) from error

    return {"pub_name": pub_name}
