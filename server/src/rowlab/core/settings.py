"""App settings stored in the local database. Secrets are never returned by the API."""

import os
from typing import Literal

from pydantic import BaseModel, Field

from rowlab.core import db
from rowlab.core.providers import openrouter

OPENROUTER_KEY = "openrouter_api_key"


class Settings(BaseModel):
    openrouter_key: Literal["environment", "saved"] | None = Field(
        description="Where the OpenRouter API key comes from, if set. The key is never returned."
    )


def get_settings() -> Settings:
    if os.environ.get("OPENROUTER_API_KEY"):
        return Settings(openrouter_key="environment")
    return Settings(openrouter_key="saved" if _get(OPENROUTER_KEY) else None)


def openrouter_key() -> str | None:
    """`OPENROUTER_API_KEY` if set, otherwise the key saved in the UI."""
    return os.environ.get("OPENROUTER_API_KEY") or _get(OPENROUTER_KEY)


def save_openrouter_key(key: str) -> Settings:
    key = key.strip()
    openrouter.check_key(key)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (OPENROUTER_KEY, key)
        )
    return get_settings()


def _get(key: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
