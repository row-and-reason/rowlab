import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rowlab import __version__
from rowlab.api import datasets, jobs, runs, settings
from rowlab.core import runs as runs_core
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers.openrouter import OpenRouterError

STATIC_DIR = Path(__file__).parent / "static"


class Health(BaseModel):
    status: str
    version: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs execute in the server process, so any still marked running were cut off by a restart.
    runs_core.fail_interrupted_runs()
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

    @app.get("/v1/health", operation_id="getHealth")
    def health() -> Health:
        return Health(status="ok", version=__version__)

    app.include_router(datasets.router)
    app.include_router(jobs.router)
    app.include_router(runs.router)
    app.include_router(settings.router)

    # Core errors become the same `{"detail": ...}` body FastAPI uses for its own errors.
    @app.exception_handler(NotFound)
    def not_found(request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(InvalidRequest)
    def invalid_request(request: Request, exc: InvalidRequest) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(OpenRouterError)
    def openrouter_error(request: Request, exc: OpenRouterError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    # The built web UI, bundled into the package by `make build`. Mounted last so API routes win.
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")

    return app


app = create_app()
