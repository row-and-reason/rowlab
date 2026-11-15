"""What the app needs to know about the server and the organisation's setup."""

from typing import Literal

from pydantic import BaseModel, Field

from rowlab.core import model_providers
from rowlab.core.config import config


class Settings(BaseModel):
    provider: Literal["server", "organisation"] | None = Field(
        description="Where model calls go: the server's own key (`OPENROUTER_API_KEY`), the "
        "organisation's active provider, or nowhere yet."
    )
    mode: Literal["local", "hosted"] = Field(
        description="`local`: one person on their own machine. `hosted`: shared, with sign-in."
    )
    server_files: bool = Field(
        description="Whether datasets can be added from, and exported to, paths on the server."
    )


def get_settings(org_id: str) -> Settings:
    return Settings(
        provider=model_providers.status(org_id),
        mode=config().mode,
        server_files=config().server_files,
    )
