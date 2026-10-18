import json
import re
from html import escape
from typing import Literal
from urllib.parse import urlsplit

import aiofiles
import fastapi
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from web_config import SETTINGS_PATH
from pretty_notebook.appearance import validate_appearance

from .atomic_io import atomic_write_text
from .permissions import require_permission

router = fastapi.APIRouter()
WEB_SETTINGS_PATH = SETTINGS_PATH
STYLE_NAME = re.compile(r"[A-Za-z0-9_-]+\Z")


class PNBPWebLayout(BaseModel):
    """Validated owner-controlled presentation settings."""

    NAV_BRAND: str = Field(max_length=10_000)
    NAV_PAGES: dict[str, str | list[dict[str, str]]]
    FOOTER: str = Field(max_length=50_000)
    TITLE: str = Field(max_length=500)

    APPEARANCE: dict = Field(default_factory=dict)

    @field_validator("APPEARANCE")
    @classmethod
    def valid_appearance(cls, value):
        return validate_appearance(value)

    darkmode: bool
    hljs_light: str = Field(max_length=100)
    hljs_dark: str = Field(max_length=100)
    merm_light: Literal["default", "dark", "forest", "neutral", "base"]
    merm_dark: Literal["default", "dark", "forest", "neutral", "base"]

    @field_validator("hljs_light", "hljs_dark")
    @classmethod
    def valid_style_name(cls, value: str) -> str:
        if not STYLE_NAME.fullmatch(value):
            raise ValueError(
                "Highlight style names may contain letters, numbers, _ and -"
            )
        return value

    @field_validator("NAV_PAGES")
    @classmethod
    def valid_navigation(cls, pages: dict[str, str | list[dict[str, str]]]):
        if len(pages) > 100:
            raise ValueError("Navigation may contain at most 100 top-level entries")

        links = []
        for label, value in pages.items():
            if not label or len(label) > 200:
                raise ValueError("Navigation labels must contain 1 to 200 characters")
            if isinstance(value, str):
                links.append(value)
            else:
                if len(value) > 100:
                    raise ValueError(
                        "Navigation dropdowns may contain at most 100 entries"
                    )
                for entry in value:
                    for child_label, url in entry.items():
                        if not child_label or len(child_label) > 200:
                            raise ValueError(
                                "Navigation labels must contain 1 to 200 characters"
                            )
                        links.append(url)

        for url in links:
            if any(ord(character) < 32 for character in url) or "\\" in url:
                raise ValueError("Navigation contains an invalid URL")
            if url.startswith("/") and not url.startswith("//"):
                continue
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("Navigation URLs must be local paths or HTTPS URLs")

        return pages


async def render_nav(pages: dict, prefix=""):
    """Render escaped links and native, keyboard-operable dropdowns."""
    def link(label, url):
        target = escape(prefix + url if url.startswith("/") else url, quote=True)
        return f'<a class="nav-link" href="{target}">{escape(label)}</a>'

    items = []
    for label, value in pages.items():
        if isinstance(value, str):
            items.append(f'<li>{link(label, value)}</li>')
        else:
            children = "".join(
                f'<li>{link(child_label, url)}</li>'
                for entry in value for child_label, url in entry.items()
            )
            items.append(
                '<li><details class="nav-group">'
                f'<summary>{escape(label)}</summary>'
                f'<ul class="nav-children">{children}</ul></details></li>'
            )
    return "".join(items)


async def get_layout_content(prefix=""):
    """Read, validate, and prepare presentation settings for rendering."""
    async with aiofiles.open(WEB_SETTINGS_PATH, mode="r") as f:
        settings = PNBPWebLayout.model_validate_json(await f.read()).model_dump()
        settings["APPEARANCE"] = validate_appearance(settings["APPEARANCE"])
        settings["NAV_PAGES"] = await render_nav(settings["NAV_PAGES"], prefix)

    return settings


async def update_layout(
    NAV_BRAND: str,
    NAV_PAGES: dict,
    FOOTER: str,
    TITLE: str,
    darkmode: bool,
    hljs_light: str,
    hljs_dark: str,
    merm_light: str,
    merm_dark: str,
    appearance: dict | None = None,
):
    """Atomically persist validated presentation settings."""
    lout = {
        "APPEARANCE": validate_appearance(appearance or {}),
        "NAV_BRAND": NAV_BRAND,
        "NAV_PAGES": NAV_PAGES,
        "FOOTER": FOOTER,
        "TITLE": TITLE,
        "darkmode": darkmode,
        "hljs_light": hljs_light,
        "hljs_dark": hljs_dark,
        "merm_light": merm_light,
        "merm_dark": merm_dark,
    }

    await atomic_write_text(WEB_SETTINGS_PATH, json.dumps(lout, indent=4))

    return lout


@router.post(
    "/api/layout",
    name="update_lout",
    status_code=201,
    response_model=PNBPWebLayout,
    dependencies=[Depends(require_permission("site"))],
)
async def layout_post(lout_in: PNBPWebLayout, request: Request):
    """Post Layout"""
    try:
        request.app.state.assets.validate_layout(lout_in.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    nb = lout_in.NAV_BRAND
    np = lout_in.NAV_PAGES
    f = lout_in.FOOTER
    t = lout_in.TITLE
    dm = lout_in.darkmode
    hll = lout_in.hljs_light
    hld = lout_in.hljs_dark
    mml = lout_in.merm_light
    mmd = lout_in.merm_dark

    async with request.app.state.storage_lock:
        return await update_layout(nb, np, f, t, dm, hll, hld, mml, mmd, lout_in.APPEARANCE)
