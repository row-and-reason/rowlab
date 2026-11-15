"""Model providers: where an organisation's model calls go, on its own key. An organisation saves any
number of them, OpenRouter or LiteLLM, each a base URL and an API key; one is active, and new runs use
it. A run keeps the provider it started with, so its answers and costs come from one place.

`OPENROUTER_API_KEY`, when set, is the server's own key, used for every organisation's runs instead
(`paid_by` "server").

Base URLs are reached like any address the server fetches on someone's behalf (`network.check_url`):
hosted, only public addresses, or the hosts the operator names in `ROWLAB_PRIVATE_HOSTS`. They are
checked when saved, and again before each chunk of a run.
"""

import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from rowlab.core import catalog, crypto, db, network, tasks
from rowlab.core.config import config
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers import litellm, model_api, openrouter
from rowlab.core.providers.model_api import ProviderError, Request
from rowlab.core.tasks import Task

ProviderType = Literal["openrouter", "litellm"]
ACTIVE = "active_provider"  # the setting naming the active provider
NO_PROVIDER = "Add a model provider in Settings → Providers first."

_MODULES = {"openrouter": openrouter, "litellm": litellm}
_LABELS = {"openrouter": "OpenRouter", "litellm": "LiteLLM"}


class ProviderInput(BaseModel):
    name: str = Field("", description="Defaults to the type's name, e.g. `OpenRouter`.")
    type: ProviderType
    base_url: str = Field(
        "",
        description="Where its API is. Empty for OpenRouter's own, `https://openrouter.ai/api`. For "
        "LiteLLM, the gateway's address, e.g. `https://litellm.example.com`.",
    )
    model_prefix: str = Field(
        "",
        description="Put before rowlab's model ids, for a gateway that routes them under a prefix, "
        "e.g. `openrouter/`.",
    )
    api_key: str | None = Field(
        None, description="Required for a new provider; leave out to keep the saved one."
    )


class Provider(BaseModel):
    """A provider as the API shows it: without its key."""

    id: str
    name: str
    type: ProviderType
    base_url: str
    model_prefix: str
    active: bool = Field(description="Whether new runs use it.")
    created_at: datetime


class Use(BaseModel):
    """Where a run's calls go, and on whose key."""

    type: ProviderType
    base_url: str
    api_key: str
    model_prefix: str = ""
    paid_by: Literal["organisation", "server"] = "organisation"


def server_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY") or None


def list_providers(org_id: str) -> list[Provider]:
    active = _active_id(org_id)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM providers WHERE org_id = ? ORDER BY name", (org_id,)
        ).fetchall()
    return [_from_row(row, active) for row in rows]


def get_provider(org_id: str, provider_id: str) -> Provider:
    return _from_row(_row(org_id, provider_id), _active_id(org_id))


def create_provider(org_id: str, data: ProviderInput) -> Provider:
    """Save a provider once it accepts the key. The organisation's first is active."""
    if not (data.api_key or "").strip():
        raise InvalidRequest("Enter the API key.")
    fields = _checked(data, data.api_key)
    provider_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO providers (id, org_id, name, type, base_url, model_prefix, api_key,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (provider_id, org_id, *fields, datetime.now(UTC).isoformat()),
        )
    if _active_id(org_id) is None:
        activate(org_id, provider_id)
    return get_provider(org_id, provider_id)


def update_provider(org_id: str, provider_id: str, data: ProviderInput) -> Provider:
    """Change a provider; its key stays as saved unless a new one is given. Checked like a new one."""
    saved = _row(org_id, provider_id)
    fields = _checked(data, data.api_key or crypto.decrypt(saved["api_key"]))
    with db.connect() as conn:
        conn.execute(
            "UPDATE providers SET name = ?, type = ?, base_url = ?, model_prefix = ?, api_key = ?"
            " WHERE id = ?",
            (*fields, provider_id),
        )
    return get_provider(org_id, provider_id)


def delete_provider(org_id: str, provider_id: str) -> None:
    """Delete a provider. If it was active, none is until another is picked. Runs that used it fail
    on their next chunk, saying so."""
    _row(org_id, provider_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        conn.execute(
            "DELETE FROM settings WHERE org_id = ? AND key = ? AND value = ?",
            (org_id, ACTIVE, provider_id),
        )


def activate(org_id: str, provider_id: str) -> Provider:
    """Make a provider the one new runs use."""
    _row(org_id, provider_id)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (org_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (org_id, key) DO UPDATE SET value = excluded.value",
            (org_id, ACTIVE, provider_id),
        )
    return get_provider(org_id, provider_id)


def status(org_id: str) -> Literal["server", "organisation"] | None:
    """Where model calls go: the server's key, the organisation's active provider, or nowhere yet."""
    if server_key():
        return "server"
    return "organisation" if _active_id(org_id) else None


def for_new_run(org_id: str) -> tuple[str | None, ProviderType]:
    """The provider a new run keeps (none on the server's key), and its type."""
    if server_key():
        return None, "openrouter"
    active = _active_id(org_id)
    if active is None:
        raise InvalidRequest(NO_PROVIDER)
    return active, _row(org_id, active)["type"]


def active_type(org_id: str) -> ProviderType:
    """The type of provider a new run would use: OpenRouter's, until one is set."""
    try:
        return for_new_run(org_id)[1]
    except InvalidRequest:
        return "openrouter"


def for_run(org_id: str, provider_id: str | None) -> Use:
    """Where a run's calls go: the provider it started with; or the server's key, if it started on
    it (or before providers) and it is still set; or else the active provider."""
    if provider_id is None and server_key():
        return Use(
            type="openrouter", base_url=openrouter.BASE_URL, api_key=server_key(), paid_by="server"
        )
    provider_id = provider_id or _active_id(org_id)
    if provider_id is None:
        raise InvalidRequest(NO_PROVIDER)
    try:
        row = _row(org_id, provider_id)
    except NotFound:
        raise InvalidRequest(
            "The model provider this run used was deleted. Start the run again."
        ) from None
    _check_url(row["base_url"])
    return Use(
        type=row["type"],
        base_url=row["base_url"],
        api_key=crypto.decrypt(row["api_key"]),
        model_prefix=row["model_prefix"],
    )


def check_model(provider_type: ProviderType, model: str) -> None:
    """Raise InvalidRequest if the provider can't run the model."""
    if provider_type == "litellm" and catalog.kind(model) == "decision":
        raise InvalidRequest(
            f"{tasks.model_slug(model)} is a decision model, which only OpenRouter providers run."
        )


def request(model_prefix: str, task: Task, model: str, prompt: str) -> Request:
    """The call asking one task of one model, about one row's prompt."""
    if catalog.kind(model) == "decision":
        return openrouter.decision_request(model, prompt, tasks.decision_questions(task))
    return model_api.completion_request(
        model,
        tasks.llm_messages(task, prompt),
        tasks.llm_schema(task),
        name=model_prefix + model if model_prefix else None,
    )


class Reply(BaseModel):
    """A model's reply: the decision answers by question, or the chat message's text."""

    data: Any
    cost: float
    input_tokens: int = 0
    output_tokens: int = 0


def ask(use: Use, request: Request) -> Reply:
    """Make a call, paid for. When the provider doesn't say what it cost, it is worked out from the
    model's prices and the tokens used."""
    reply = model_api.post(use.base_url, request, use.api_key)
    data = (
        openrouter.answers(reply)
        if request.path == openrouter.DECISIONS
        else model_api.message(reply)
    )
    cost, input_tokens, output_tokens = model_api.usage(reply)
    if cost is None:
        model = catalog.get(request.model)
        cost = input_tokens * model.prompt_price + output_tokens * model.completion_price
    return Reply(data=data, cost=cost, input_tokens=input_tokens, output_tokens=output_tokens)


def _checked(data: ProviderInput, api_key: str) -> tuple[str, str, str, str, str]:
    """The fields to save, once the provider accepts the key at its base URL."""
    base_url = data.base_url.strip().rstrip("/").removesuffix("/v1").rstrip("/")
    if not base_url:
        if data.type != "openrouter":
            raise InvalidRequest(f"Enter the {_LABELS[data.type]} gateway's address.")
        base_url = openrouter.BASE_URL
    if "://" not in base_url:
        base_url = f"https://{base_url}"
    _check_url(base_url)
    api_key = api_key.strip()
    try:
        _MODULES[data.type].check_key(base_url, api_key)
    except ProviderError as e:
        raise InvalidRequest(f"{_LABELS[data.type]} did not accept the key: {e}") from e
    name = data.name.strip() or _LABELS[data.type]
    return name, data.type, base_url, data.model_prefix.strip(), crypto.encrypt(api_key)


def _check_url(base_url: str) -> None:
    """OpenRouter's own address needs no check."""
    if base_url != openrouter.BASE_URL:
        network.check_url(base_url, config().private_hosts)


def _active_id(org_id: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE org_id = ? AND key = ?", (org_id, ACTIVE)
        ).fetchone()
    return row["value"] if row else None


def _row(org_id: str, provider_id: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ? AND org_id = ?", (provider_id, org_id)
        ).fetchone()
    if row is None:
        raise NotFound(f"Provider {provider_id} not found")
    return row


def _from_row(row, active: str | None) -> Provider:
    return Provider(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        base_url=row["base_url"],
        model_prefix=row["model_prefix"],
        active=row["id"] == active,
        created_at=row["created_at"],
    )
