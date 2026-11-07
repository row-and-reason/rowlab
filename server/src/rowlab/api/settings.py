from fastapi import APIRouter
from pydantic import BaseModel

from rowlab.api.auth import CanAdmin, CanRead
from rowlab.core import auth, settings, usage
from rowlab.core.auth import ApiKey, NewApiKey
from rowlab.core.settings import Settings
from rowlab.core.usage import Usage

router = APIRouter(prefix="/v1/settings", tags=["settings"])


class OpenRouterKey(BaseModel):
    key: str


class ApiKeyRequest(BaseModel):
    name: str


@router.get("", operation_id="getSettings")
def get_settings(me: CanRead) -> Settings:
    return settings.get_settings(me.org.id)


@router.put("/openrouter-key", operation_id="saveOpenRouterKey")
def save_openrouter_key(body: OpenRouterKey, me: CanAdmin) -> Settings:
    """Check the key with OpenRouter and save it for the organisation."""
    return settings.save_openrouter_key(me.org.id, body.key)


@router.get("/api-keys", operation_id="listApiKeys")
def list_api_keys(me: CanRead) -> list[ApiKey]:
    """Your own API keys. Hosted only: locally the API needs no key."""
    return auth.list_api_keys(me)


@router.post("/api-keys", operation_id="createApiKey", status_code=201)
def create_api_key(body: ApiKeyRequest, me: CanRead) -> NewApiKey:
    """A key acting as you, with your role, sent as `Authorization: Bearer rl_…`. The key itself is
    returned only this once."""
    return auth.create_api_key(me, body.name)


@router.delete("/api-keys/{api_key_id}", operation_id="deleteApiKey", status_code=204)
def delete_api_key(api_key_id: str, me: CanRead) -> None:
    auth.delete_api_key(me, api_key_id)


@router.get("/usage", operation_id="getUsage")
def get_usage(me: CanRead, month: str | None = None) -> Usage:
    """A month's answers, spend and tokens (this month by default, as `YYYY-MM`), by day, model and
    person, and the storage the organisation's datasets take. An admin sees the organisation's;
    anyone else their own runs'."""
    return usage.month_usage(me, month)
