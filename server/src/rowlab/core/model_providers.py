"""Model providers: where an organisation's model calls go, on its own key. An organisation saves any
number of them, each a type, a base URL and an API key, by a name of its own:

- `openrouter`: OpenRouter, or anything serving its Decisions API.
- `openai`: an OpenAI-compatible server, such as a LiteLLM gateway, or vLLM serving a generic model
  or LoRA adapters (`/v1/decisions`).
- `systemone`: a server for dedicated decision models, such as vLLM or a model's own (`/v1/systemone`).

rowlab's catalog models go to the active provider; a run keeps the one it started with, so their answers
and costs come from one place. The organisation's own models (`models`) each go to their own provider.

`OPENROUTER_API_KEY`, when set, is the server's own key, used for every organisation's runs instead
(`paid_by` "server").

Base URLs are reached like any address the server fetches on someone's behalf (`network.check_url`):
hosted, only public addresses over HTTPS, or the hosts the operator names in `ROWLAB_PRIVATE_HOSTS`.
They are checked when saved, and again before each chunk of a run.
"""

import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from rowlab.core import catalog, crypto, db, network, tasks
from rowlab.core.config import config
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers import model_api, openai, openrouter, systemone
from rowlab.core.providers.model_api import ProviderError, Request
from rowlab.core.tasks import Task

ProviderType = Literal["openrouter", "openai", "systemone"]
ACTIVE = "active_provider"  # the setting naming the active provider
NO_PROVIDER = "Add OpenRouter, or a gateway, in Settings → Providers to ask rowlab's models."

_MODULES = {"openrouter": openrouter, "openai": openai, "systemone": systemone}
_LABELS = {"openrouter": "OpenRouter", "openai": "OpenAI-compatible", "systemone": "System One"}


class ProviderInput(BaseModel):
    name: str = Field(
        "",
        description="Unique in the organisation; models are added to a provider by it. Defaults to "
        "the type's name, e.g. `OpenRouter`.",
    )
    type: ProviderType = Field(
        description="`openrouter`; `openai` for an OpenAI-compatible server (LiteLLM, or vLLM for "
        "generic models and LoRA adapters); `systemone` for a server of dedicated decision models "
        "(vLLM, or a model's own)."
    )
    base_url: str = Field(
        "",
        description="Where its API is. Empty for OpenRouter's own, `https://openrouter.ai/api`; "
        "otherwise the server's address, e.g. `https://litellm.example.com`.",
    )
    model_prefix: str = Field(
        "",
        description="`openai` only: put before rowlab's catalog ids, for a gateway that routes them "
        "under a prefix, e.g. `openrouter/`.",
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
    active: bool = Field(description="Whether new runs ask rowlab's catalog models through it.")
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
            "SELECT * FROM providers WHERE org_id = ? ORDER BY lower(name), name", (org_id,)
        ).fetchall()
    return [_from_row(row, active) for row in rows]


def get_provider(org_id: str, provider_id: str) -> Provider:
    return _from_row(_row(org_id, provider_id), _active_id(org_id))


def create_provider(org_id: str, data: ProviderInput) -> Provider:
    """Save a provider once it accepts the key. The organisation's first that can serve rowlab's
    catalog models is active."""
    if not (data.api_key or "").strip():
        raise InvalidRequest("Enter the API key.")
    fields = _checked(org_id, None, data, data.api_key)
    provider_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO providers (id, org_id, name, type, base_url, model_prefix, api_key,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (provider_id, org_id, *fields, datetime.now(UTC).isoformat()),
        )
    if _active_id(org_id) is None and data.type != "systemone":
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
    fields = _checked(org_id, provider_id, data, data.api_key or crypto.decrypt(saved["api_key"]))
    with db.connect() as conn:
        conn.execute(
            "UPDATE providers SET name = ?, type = ?, base_url = ?, model_prefix = ?, api_key = ?"
            " WHERE id = ?",
            (*fields, provider_id),
        )
    return get_provider(org_id, provider_id)


def move(org_id: str, name_or_id: str, base_url: str, api_key: str) -> Provider:
    """Point a provider, by name or id, at a new address with its key: a rented GPU's server, say,
    started again elsewhere. Its models and the runs that ask them keep going there."""
    saved = find(org_id, name_or_id)
    data = ProviderInput(
        name=saved.name,
        type=saved.type,
        base_url=base_url,
        model_prefix=saved.model_prefix,
        api_key=api_key,
    )
    return update_provider(org_id, saved.id, data)


def delete_provider(org_id: str, provider_id: str) -> None:
    """Delete a provider, once no model of the organisation's own uses it. If it was active, none is
    until another is picked. Runs that used it fail on their next chunk, saying so."""
    _row(org_id, provider_id)
    with db.connect() as conn:
        used = conn.execute(
            "SELECT id FROM models WHERE org_id = ? AND provider_id = ? AND deleted_at IS NULL"
            " ORDER BY id",
            (org_id, provider_id),
        ).fetchall()
        if used:
            raise InvalidRequest(f"Delete its models first: {', '.join(r['id'] for r in used)}.")
        conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        conn.execute(
            "DELETE FROM settings WHERE org_id = ? AND key = ? AND value = ?",
            (org_id, ACTIVE, provider_id),
        )


def activate(org_id: str, provider_id: str) -> Provider:
    """Make a provider the one new runs ask rowlab's catalog models through."""
    if _row(org_id, provider_id)["type"] == "systemone":
        raise InvalidRequest(
            "A System One server answers only the models added to it, not rowlab's catalog."
        )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (org_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (org_id, key) DO UPDATE SET value = excluded.value",
            (org_id, ACTIVE, provider_id),
        )
    return get_provider(org_id, provider_id)


def status(org_id: str) -> Literal["server", "organisation"] | None:
    """Where model calls go: the server's key, the organisation's providers, or nowhere yet."""
    if server_key():
        return "server"
    with db.connect() as conn:
        found = conn.execute("SELECT 1 FROM providers WHERE org_id = ?", (org_id,)).fetchone()
    return "organisation" if found else None


def find(org_id: str, name_or_id: str) -> Provider:
    """A provider by its name, or its id. Raises InvalidRequest, naming the organisation's providers,
    for none or two by that name (from before names were unique)."""
    providers = list_providers(org_id)
    found = [p for p in providers if p.id == name_or_id] or [
        p for p in providers if p.name == name_or_id
    ]
    if len(found) == 1:
        return found[0]
    if found:
        raise InvalidRequest(
            f"Two providers are named {name_or_id}. Rename one in Settings → Providers, or give its id."
        )
    names = ", ".join(p.name for p in providers) or "none yet"
    raise InvalidRequest(f"No provider is named {name_or_id}. The organisation's: {names}.")


def for_new_run(org_id: str) -> str | None:
    """The provider a new run keeps for catalog models: the active one, or none on the server's key."""
    if server_key():
        return None
    active = _active_id(org_id)
    if active is None:
        raise InvalidRequest(NO_PROVIDER)
    return active


def for_run(org_id: str, provider_id: str | None) -> Use:
    """Where a run's calls go: the provider it started with (or its model's own); or the server's
    key, if it started on it (or before providers) and it is still set; or else the active provider."""
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
    provider_type: ProviderType, task: Task, model: catalog.Model, prompt: str, *, prefix: str = ""
) -> Request:
    """The call asking one task of one model, about one row's prompt, as the provider takes it. The
    provider calls an organisation's own model by its `upstream` name, and a catalog model by its id,
    after the provider's `prefix`."""
    name = model.upstream or prefix + model.id
    if model.kind == "decision":
        questions = tasks.decision_questions(task)
        return _MODULES[provider_type].decision_request(model.id, name, prompt, questions)
    return model_api.completion_request(
        model.id, tasks.llm_messages(task, prompt), tasks.llm_schema(task), name=name
    )


class Reply(BaseModel):
    """A model's reply: the decision answers by question, or the chat message's text."""

    data: Any
    cost: float
    input_tokens: int = 0
    output_tokens: int = 0


def ask(
    use: Use,
    request: Request,
    model: catalog.Model,
    *,
    attempts: int = model_api.ATTEMPTS,
    timeout: float = model_api.TIMEOUT_SECONDS,
) -> Reply:
    """Make a call, paid for. `data` is None when the reply can't be read. When the provider doesn't
    say what it cost, it is worked out from the model's prices and the tokens used: nothing, for a
    model without prices."""
    reply = model_api.post(use.base_url, request, use.api_key, attempts=attempts, timeout=timeout)
    try:
        if request.path == model_api.COMPLETIONS:
            data = model_api.message(reply)
        else:
            data = _MODULES[use.type].answers(reply)
    except (KeyError, IndexError, TypeError, AttributeError):
        data = None  # Paid for, but not in a shape rowlab reads: that answer fails.
    cost, input_tokens, output_tokens = model_api.usage(reply)
    if cost is None:
        cost = input_tokens * (model.prompt_price or 0) + output_tokens * (
            model.completion_price or 0
        )
    return Reply(data=data, cost=cost, input_tokens=input_tokens, output_tokens=output_tokens)


def _base_url(data: ProviderInput) -> str:
    """The base URL as saved: with a scheme, without a trailing `/v1`; OpenRouter's if none."""
    base_url = data.base_url.strip().rstrip("/").removesuffix("/v1").rstrip("/")
    if not base_url:
        if data.type != "openrouter":
            raise InvalidRequest("Enter the server's address.")
        return openrouter.BASE_URL
    return base_url if "://" in base_url else f"https://{base_url}"


def _checked(
    org_id: str, provider_id: str | None, data: ProviderInput, api_key: str
) -> tuple[str, str, str, str, str]:
    """The fields to save, once the provider accepts the key at its base URL."""
    name = data.name.strip() or _LABELS[data.type]
    with db.connect() as conn:
        taken = conn.execute(
            "SELECT 1 FROM providers WHERE org_id = ? AND name = ? AND id != ?",
            (org_id, name, provider_id or ""),
        ).fetchone()
        # Two may share a name from before names were unique: each can still change, keeping it.
        kept = (
            provider_id
            and conn.execute(
                "SELECT 1 FROM providers WHERE id = ? AND name = ?", (provider_id, name)
            ).fetchone()
        )
    if taken and not kept:
        raise InvalidRequest(f"A provider is already named {name}. Give this one another name.")
    base_url = _base_url(data)
    _check_url(base_url)
    api_key = api_key.strip()
    try:
        _MODULES[data.type].check_key(base_url, api_key)
    except ProviderError as e:
        if e.unreachable:
            raise InvalidRequest(f"{e}. Is the server up? Save the provider once it is.") from e
        raise InvalidRequest(f"{_LABELS[data.type]} did not accept the key: {e}") from e
    # OpenRouter names models as rowlab does; only a gateway routes them under a prefix.
    prefix = data.model_prefix.strip() if data.type == "openai" else ""
    return name, data.type, base_url, prefix, crypto.encrypt(api_key)


def _check_url(base_url: str) -> None:
    """OpenRouter's own address needs no check. Where private URLs aren't allowed (hosted), a key
    goes to a public server only over HTTPS; plain HTTP is for the hosts the operator names."""
    if base_url == openrouter.BASE_URL:
        return
    network.check_url(base_url, config().private_hosts)
    private = config().private_urls or urlparse(base_url).hostname in config().private_hosts
    if base_url.startswith("http://") and not private:
        raise InvalidRequest(
            "Use an https:// address: the key would go to a public server unencrypted. For a GPU "
            "server, a tunnel (`cloudflared tunnel --url http://localhost:8000`) or the host's "
            "HTTPS proxy gives one."
        )


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
