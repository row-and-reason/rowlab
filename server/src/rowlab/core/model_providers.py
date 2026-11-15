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
    """Change a provider; its key stays as saved unless a new one is given. Checked like a new one.
    Its type can't change, and its address only with the key entered again: a saved key goes only
    where it was first sent."""
    saved = _row(org_id, provider_id)
    if data.type != saved["type"]:
        raise InvalidRequest("A provider's type can't change. Add a new provider instead.")
    if not data.api_key and _base_url(data) != saved["base_url"]:
        raise InvalidRequest("Enter the API key again to change the base URL.")
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


def for_new_run(org_id: str) -> str | None:
    """The provider a new run keeps: the active one, or none on the server's key."""
    if server_key():
        return None
    active = _active_id(org_id)
    if active is None:
        raise InvalidRequest(NO_PROVIDER)
    return active


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
    try:
        _check_url(row["base_url"])
    except network.Unresolved:
        pass  # Perhaps for a moment: each call fails on its own, and is retried.
    return Use(
        type=row["type"],
        base_url=row["base_url"],
        api_key=crypto.decrypt(row["api_key"]),
        model_prefix=row["model_prefix"],
    )


def request(
    provider_type: ProviderType,
    model_prefix: str,
    task: Task,
    model: str,
    prompt: str,
    *,
    kind: Literal["decision", "llm"],
) -> Request:
    """The call asking one task of one model, about one row's prompt, as the provider takes it."""
    name = model_prefix + model
    if kind == "decision":
        questions = tasks.decision_questions(task)
        if provider_type == "litellm":
            return litellm.decision_request(model, name, prompt, questions)
        return openrouter.decision_request(model, prompt, questions)
    return model_api.completion_request(
        model, tasks.llm_messages(task, prompt), tasks.llm_schema(task), name=name
    )


class Reply(BaseModel):
    """A model's reply: the decision answers by question, or the chat message's text."""

    data: Any
    cost: float
    input_tokens: int = 0
    output_tokens: int = 0


def ask(use: Use, request: Request, model: catalog.Model) -> Reply:
    """Make a call, paid for. `data` is None when the reply can't be read. When the provider doesn't
    say what it cost, it is worked out from the model's prices and the tokens used."""
    reply = model_api.post(use.base_url, request, use.api_key)
    try:
        if request.path == openrouter.DECISIONS:
            data = openrouter.answers(reply)
        elif request.path == litellm.DECISIONS:
            data = litellm.answers(reply)
        else:
            data = model_api.message(reply)
    except (KeyError, IndexError, TypeError, AttributeError):
        data = None  # Paid for, but not in a shape rowlab reads: that answer fails.
    cost, input_tokens, output_tokens = model_api.usage(reply)
    if cost is None:
        cost = input_tokens * model.prompt_price + output_tokens * model.completion_price
    return Reply(data=data, cost=cost, input_tokens=input_tokens, output_tokens=output_tokens)


def _base_url(data: ProviderInput) -> str:
    """The base URL as saved: with a scheme, without a trailing `/v1`; OpenRouter's if none."""
    base_url = data.base_url.strip().rstrip("/").removesuffix("/v1").rstrip("/")
    if not base_url:
        if data.type != "openrouter":
            raise InvalidRequest(f"Enter the {_LABELS[data.type]} gateway's address.")
        return openrouter.BASE_URL
    return base_url if "://" in base_url else f"https://{base_url}"


def _checked(data: ProviderInput, api_key: str) -> tuple[str, str, str, str, str]:
    """The fields to save, once the provider accepts the key at its base URL."""
    base_url = _base_url(data)
    _check_url(base_url)
    api_key = api_key.strip()
    try:
        _MODULES[data.type].check_key(base_url, api_key)
    except ProviderError as e:
        raise InvalidRequest(f"{_LABELS[data.type]} did not accept the key: {e}") from e
    name = data.name.strip() or _LABELS[data.type]
    # OpenRouter names models as rowlab does; only a gateway routes them under a prefix.
    prefix = data.model_prefix.strip() if data.type == "litellm" else ""
    return name, data.type, base_url, prefix, crypto.encrypt(api_key)


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
