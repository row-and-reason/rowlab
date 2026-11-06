from fastapi import APIRouter
from pydantic import BaseModel

from rowlab.core import settings
from rowlab.core.settings import Settings

router = APIRouter(tags=["settings"])


class OpenRouterKey(BaseModel):
    key: str


@router.get("/v1/settings", operation_id="getSettings")
def get_settings() -> Settings:
    return settings.get_settings()


@router.put("/v1/settings/openrouter-key", operation_id="saveOpenRouterKey")
def save_openrouter_key(body: OpenRouterKey) -> Settings:
    """Check the key with OpenRouter and save it locally."""
    return settings.save_openrouter_key(body.key)
