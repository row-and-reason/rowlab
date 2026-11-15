from fastapi import APIRouter

from rowlab.api.auth import CanAdmin, CanRead
from rowlab.core import model_providers
from rowlab.core.model_providers import Provider, ProviderInput

router = APIRouter(prefix="/v1/settings/providers", tags=["settings"])


@router.get("", operation_id="listProviders")
def list_providers(me: CanRead) -> list[Provider]:
    """The organisation's model providers, by name, and which one new runs use. Keys are never
    returned."""
    return model_providers.list_providers(me.org.id)


@router.post("", operation_id="createProvider", status_code=201)
def create_provider(data: ProviderInput, me: CanAdmin) -> Provider:
    """Save a provider once it accepts the key. The organisation's first becomes active."""
    return model_providers.create_provider(me.org.id, data)


@router.put("/{provider_id}", operation_id="updateProvider")
def update_provider(provider_id: str, data: ProviderInput, me: CanAdmin) -> Provider:
    """Change a provider; leave out `api_key` to keep the saved one."""
    return model_providers.update_provider(me.org.id, provider_id, data)


@router.post("/{provider_id}/activate", operation_id="activateProvider")
def activate_provider(provider_id: str, me: CanAdmin) -> Provider:
    """Make the provider the one new runs use. Runs already started keep theirs."""
    return model_providers.activate(me.org.id, provider_id)


@router.delete("/{provider_id}", operation_id="deleteProvider", status_code=204)
def delete_provider(provider_id: str, me: CanAdmin) -> None:
    model_providers.delete_provider(me.org.id, provider_id)
