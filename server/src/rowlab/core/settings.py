"""App settings stored in the local database. Secrets are never returned by the API."""

import os
from typing import Literal

from pydantic import BaseModel, Field

from rowlab.core import db
from rowlab.core.config import config
from rowlab.core.providers import openrouter

OPENROUTER_KEY = "openrouter_api_key"


class Settings(BaseModel):
    openrouter_key: Literal["environment", "saved"] | None = Field(
        description="Where the OpenRouter API key comes from, if set. The key is never returned."
    )
    mode: Literal["local", "hosted"] = Field(
        description="`local`: one person on their own machine. `hosted`: shared, with sign-in."
    )
    server_files: bool = Field(
        description="Whether datasets can be added from, and exported to, paths on the server."
    )


def get_settings() -> Settings:
    if os.environ.get("OPENROUTER_API_KEY"):
        key = "environment"
    else:
        key = "saved" if _get(OPENROUTER_KEY) else None
    return Settings(openrouter_key=key, mode=config().mode, server_files=config().server_files)


def openrouter_key() -> str | None:
    """`OPENROUTER_API_KEY` if set, otherwise the key saved in the UI."""
    return os.environ.get("OPENROUTER_API_KEY") or _get(OPENROUTER_KEY)


def save_openrouter_key(key: str) -> Settings:
    key = key.strip()
    openrouter.check_key(key)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (OPENROUTER_KEY, key),
        )
    return get_settings()


def _get(key: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
