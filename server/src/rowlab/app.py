import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.routing import Mount

from rowlab import __version__
from rowlab.api import auth, connections, datasets, members, runs, settings, utils
from rowlab.core import runs as runs_core
from rowlab.core.config import config
from rowlab.core.errors import Forbidden, InvalidRequest, NotFound, Unauthorized
from rowlab.core.providers.openrouter import OpenRouterError
from rowlab.mcp.server import create_server

STATIC_DIR = Path(__file__).parent / "static"


class Health(BaseModel):
    status: str
    version: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs execute in this process, unless runners run on their own (`rowlab serve --no-runner`).
    if not os.environ.get("ROWLAB_NO_RUNNER"):
        runs_core.start_runner()
    # The MCP app, mounted below, has sessions to start and stop.
    async with app.state.mcp.lifespan(app.state.mcp):
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="rowlab", version=__version__, lifespan=lifespan)

    # Only needed in development, when the web app runs on its own dev server.
    cors_origins = os.environ.get("ROWLAB_CORS_ORIGINS")
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins.split(","),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Uploads past the file limit are refused before they are read, so they never fill the disk:
    # the server reads no more than an upload's stated length, which must be given.
    @app.middleware("http")
    async def limit_uploads(request: Request, call_next):
        length = request.headers.get("content-length", "")
        if request.headers.get("content-type", "").startswith("multipart/") and not length:
            return JSONResponse({"detail": "Send uploads with a Content-Length."}, status_code=411)
        if length.isdigit() and int(length) > config().max_file_bytes + 1_000_000:
            return JSONResponse(
                {"detail": "The file is bigger than rowlab's limit (`ROWLAB_MAX_FILE`)."},
                status_code=413,
            )
        return await call_next(request)

    @app.get("/v1/health", operation_id="getHealth")
    def health() -> Health:
        return Health(status="ok", version=__version__)

    app.include_router(auth.router)
    app.include_router(connections.router)
    app.include_router(datasets.router)
    app.include_router(members.router)
    app.include_router(runs.router)
    app.include_router(settings.router)
    app.include_router(utils.router)

    # Core errors become the same `{"detail": ...}` body FastAPI uses for its own errors.
    @app.exception_handler(NotFound)
    def not_found(request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(InvalidRequest)
    def invalid_request(request: Request, exc: InvalidRequest) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(Unauthorized)
    def unauthorized(request: Request, exc: Unauthorized) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc)}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
        )

    @app.exception_handler(Forbidden)
    def forbidden(request: Request, exc: Forbidden) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(OpenRouterError)
    def openrouter_error(request: Request, exc: OpenRouterError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    # MCP at `/mcp`, with its sign-in metadata at `/.well-known/…`, which must be at the root; the
    # built web UI (bundled into the package by `make build`) behind it. Mounted last so API routes
    # win.
    mcp = create_server()
    if STATIC_DIR.is_dir():
        # Where FastMCP keeps the routes `custom_route` adds, with the lowest precedence.
        mcp._additional_http_routes.append(Mount("/", StaticFiles(directory=STATIC_DIR, html=True)))
    app.state.mcp = mcp.http_app(path="/mcp")
    app.mount("/", app.state.mcp)

    return app


app = create_app()
