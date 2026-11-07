"""Each organisation's settings, kept in the database. Secrets are encrypted at rest when
`ROWLAB_SECRET_KEY` is set, and never returned by the API."""

import os
from typing import Literal

from pydantic import BaseModel, Field

from rowlab.core import crypto, db
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


def get_settings(org_id: str) -> Settings:
    if os.environ.get("OPENROUTER_API_KEY"):
        key = "environment"
    else:
        key = "saved" if _get(org_id, OPENROUTER_KEY) else None
    return Settings(openrouter_key=key, mode=config().mode, server_files=config().server_files)


def openrouter_key(org_id: str) -> str | None:
    """`OPENROUTER_API_KEY` if set, for every organisation, otherwise the organisation's own."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    saved = _get(org_id, OPENROUTER_KEY)
    return crypto.decrypt(saved) if saved else None


def paid_by() -> Literal["organisation", "server"]:
    """Whose key model calls go on: the server's (`OPENROUTER_API_KEY`), or else the organisation's
    own."""
    return "server" if os.environ.get("OPENROUTER_API_KEY") else "organisation"


def save_openrouter_key(org_id: str, key: str) -> Settings:
    key = key.strip()
    openrouter.check_key(key)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (org_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (org_id, key) DO UPDATE SET value = excluded.value",
            (org_id, OPENROUTER_KEY, crypto.encrypt(key)),
        )
    return get_settings(org_id)


def _get(org_id: str, key: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE org_id = ? AND key = ?", (org_id, key)
        ).fetchone()
    return row["value"] if row else None
