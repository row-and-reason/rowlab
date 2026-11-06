import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rowlab import __version__

STATIC_DIR = Path(__file__).parent / "static"


class Health(BaseModel):
    status: str
    version: str


def create_app() -> FastAPI:
    app = FastAPI(title="rowlab", version=__version__)

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

    # The built web UI, bundled into the package by `make build`. Mounted last so API routes win.
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")

    return app


app = create_app()
