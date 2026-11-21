"""What the app needs to know about the server and the organisation's setup."""

from typing import Literal

from pydantic import BaseModel, Field

from rowlab.core import datasets, model_providers
from rowlab.core.config import config


class Settings(BaseModel):
    provider: Literal["server", "organisation"] | None = Field(
        description="Where model calls go: the server's own key (`OPENROUTER_API_KEY`) for rowlab's "
        "models, the organisation's providers, or nowhere yet."
    )
    mode: Literal["local", "hosted"] = Field(
        description="`local`: one person on their own machine. `hosted`: shared, with sign-in."
    )
    server_files: bool = Field(
        description="Whether datasets can be added from, and exported to, paths on the server."
    )
    auto_settle: bool = Field(
        description="Whether the organisation's datasets settle by themselves after 24 hours of "
        "nothing happening on them, unless a dataset says otherwise. On by default."
    )


class SettingsUpdate(BaseModel):
    auto_settle: bool


def get_settings(org_id: str) -> Settings:
    return Settings(
        provider=model_providers.status(org_id),
        mode=config().mode,
        server_files=config().server_files,
        auto_settle=datasets.auto_settle(org_id),
    )


def update_settings(org_id: str, request: SettingsUpdate) -> Settings:
    datasets.set_auto_settle(org_id, request.auto_settle)
    return get_settings(org_id)
