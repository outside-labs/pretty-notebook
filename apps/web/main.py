from contextlib import asynccontextmanager
from api.process_lock import ProcessLock
from api.atomic_io import create_text_once

import fastapi
import assets
import web_config
from api import auth_api, layout_api, publish_api, publishing_api, schema, catalog, site_api
from api import forms as forms_api
from api import search_api, public_index, permissions
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from tortoise import connections
from tortoise.contrib.fastapi import RegisterTortoise, tortoise_exception_handlers
from views import forms, home
from views import search as search_view
from views import navigation as navigation_view

DEFAULT_DATABASE_URL = web_config.DATABASE_URL


def prepare_storage() -> None:
    """Create the private persistent-data layout without overwriting state."""
    for directory in {
        publish_api.PUB_PATH,
        publish_api.IMG_PATH,
        layout_api.WEB_SETTINGS_PATH.parent,
    }:
        if not directory.exists():
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)

    if not layout_api.WEB_SETTINGS_PATH.exists():
        defaults = web_config.DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8")
        create_text_once(layout_api.WEB_SETTINGS_PATH, defaults)


def create_app(
    *,
    db_url: str = DEFAULT_DATABASE_URL,
    allowed_hosts: list[str] | None = None,
    root_path: str | None = None,
) -> fastapi.FastAPI:
    """Create a worker sharing one local persistent data root."""
    if not db_url.startswith("sqlite://"):
        raise RuntimeError("The supported web profile requires a SQLite database URL.")
    asset_resolver = assets.AssetResolver(web_config.WEB_ROOT / "static", mode=web_config.asset_mode())
    prepare_storage()

    @asynccontextmanager
    async def lifespan(app):
        async with RegisterTortoise(
            app,
            db_url=db_url,
            modules={"models": ["api.auth_api", "api.forms"]},
            generate_schemas=False,
        ):
            async with app.state.storage_lock:
                app.state.schema_migration = await schema.migrate()
            app.state.publications = catalog.PublicationStore(app.state.pages_path, lock=app.state.storage_lock)
            await app.state.publications.start()
            app.state.public_index = public_index.PublicIndex(app.state.publications)
            asset_resolver.validate_layout(await layout_api.get_layout_content())
            yield

    from pretty_notebook._internal.routes import validate_prefix
    app = fastapi.FastAPI(lifespan=lifespan, exception_handlers=tortoise_exception_handlers(), root_path=validate_prefix(root_path if root_path is not None else web_config.url_prefix()))
    app.state.storage_lock = ProcessLock(layout_api.WEB_SETTINGS_PATH.parent / "site.lock")
    app.state.bootstrap_lock = app.state.storage_lock
    app.state.pages_path = publish_api.PUB_PATH
    app.state.images_path = publish_api.IMG_PATH
    app.state.settings_path = layout_api.WEB_SETTINGS_PATH
    app.state.favicon_path = layout_api.WEB_SETTINGS_PATH.parent / "favicon.png"
    app.state.favicon_lock = app.state.storage_lock
    app.state.assets = asset_resolver
    app.state.code_highlight = web_config.code_highlight()

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts or web_config.allowed_hosts(),
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        path = request.url.path.removeprefix(request.scope.get("root_path", ""))
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=()",
        )
        response.headers.setdefault("Content-Security-Policy", asset_resolver.security_policy())
        if response.status_code in {200, 206, 304} and asset_resolver.cacheable(path):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        if path.startswith("/api") or path == "/healthz":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Dynamic favicon assets must precede the repository static-file mount.
    app.include_router(site_api.router)

    app.mount(
        "/static/imgs",
        StaticFiles(directory=publish_api.IMG_PATH),
        name="published-images",
    )
    app.mount(
        "/static",
        StaticFiles(directory=web_config.WEB_ROOT / "static"),
        name="static",
    )

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        try:
            await connections.get("default").execute_query("SELECT 1")
            await layout_api.get_layout_content()
        except Exception as exc:
            raise fastapi.HTTPException(
                status_code=503,
                detail="Persistent storage is unavailable.",
            ) from exc
        return {"status": "ok"}

    app.include_router(publish_api.router)
    app.include_router(publishing_api.router)
    app.include_router(auth_api.router)
    app.include_router(permissions.router)
    app.include_router(layout_api.router)
    app.include_router(forms_api.router)
    app.include_router(search_api.router)

    @app.api_route("/api/{unknown:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
    async def unknown_api(unknown: str):
        raise fastapi.HTTPException(404, "Not Found")

    app.include_router(forms.router)
    app.include_router(search_view.router)
    app.include_router(navigation_view.router)
    # The public path catch-all must remain after every fixed and API route.
    app.include_router(home.router)

    return app


api = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(api, port=8000, host="127.0.0.1")
