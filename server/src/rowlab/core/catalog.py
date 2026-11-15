"""The models rowlab offers: a curated list (`models.toml`), in the order we'd pick them, with tags.
Prices come from OpenRouter's public catalog, refreshed hourly, or from the list when OpenRouter
can't be reached. Deprecated models aren't offered for new runs, but runs that use them still work.
"""

import logging
import time
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from rowlab.core.errors import InvalidRequest
from rowlab.core.providers import openrouter
from rowlab.core.providers.model_api import ProviderError

log = logging.getLogger(__name__)

FILE = Path(__file__).with_name("models.toml")
PRICES_TTL_SECONDS = 3600
# After OpenRouter fails to answer, the list's own prices are used for this long before asking again.
PRICES_RETRY_SECONDS = 60


class Model(BaseModel):
    id: str
    name: str
    kind: Literal["decision", "llm"]
    tags: list[str] = Field(
        description="`recommended` for the ones to try first; others (`budget`, `accurate`) to filter by."
    )
    prompt_price: float = Field(description="USD per input token.")
    completion_price: float = Field(description="USD per output token.")
    context_length: int


class _Entry(Model):
    deprecated: bool


_entries: list[_Entry] | None = None
_prices: tuple[float, dict[str, tuple[float, float]]] | None = None


def models() -> list[Model]:
    """The models offered for new runs, in the list's order."""
    return [Model(**e.model_dump(exclude={"deprecated"})) for e in _priced() if not e.deprecated]


def get(model_id: str, *, offered: bool = False) -> Model:
    """A model by id, with its prices; deprecated ones too, unless only `offered` models will do."""
    for entry in _priced():
        if entry.id == model_id:
            if offered and entry.deprecated:
                raise InvalidRequest(f"{model_id} is no longer offered. Pick another model.")
            return entry
    raise InvalidRequest(f"Unknown model: {model_id}")


def kind(model_id: str) -> Literal["decision", "llm"]:
    """Whether a model is a decision model or an LLM. Never asks OpenRouter: runs call this per row."""
    for entry in _load():
        if entry.id == model_id:
            return entry.kind
    raise InvalidRequest(f"Unknown model: {model_id}")


class ModelPage(BaseModel):
    models: list[Model]
    total: int
    next_offset: int | None


def list_models(
    search: str = "",
    kind: Literal["decision", "llm"] | None = None,
    tag: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> ModelPage:
    needle = search.lower()
    found = [
        m
        for m in models()
        if (kind is None or m.kind == kind)
        and (tag is None or tag in m.tags)
        and (needle in m.id.lower() or needle in m.name.lower())
    ]
    return ModelPage(
        models=found[offset : offset + limit],
        total=len(found),
        next_offset=offset + limit if offset + limit < len(found) else None,
    )


def _load() -> list[_Entry]:
    global _entries
    if _entries is None:
        with FILE.open("rb") as f:
            _entries = [
                _Entry(
                    id=m["id"],
                    name=m["name"],
                    kind=m["kind"],
                    tags=m.get("tags", []),
                    prompt_price=m.get("price_in", 0) / 1e6,
                    completion_price=m.get("price_out", 0) / 1e6,
                    context_length=m.get("context_length", 0),
                    deprecated=m.get("deprecated", False),
                )
                for m in tomllib.load(f)["models"]
            ]
    return _entries


def _priced() -> list[_Entry]:
    """The list, with OpenRouter's current prices where it has them."""
    global _prices
    if _prices is None or time.monotonic() > _prices[0]:
        try:
            _prices = (time.monotonic() + PRICES_TTL_SECONDS, openrouter.prices())
        # Unreachable, or answering in a shape it didn't before: the list's own prices will do.
        except (ProviderError, KeyError, TypeError, ValueError) as e:
            log.warning("Using the model list's own prices: %s", e)
            _prices = (time.monotonic() + PRICES_RETRY_SECONDS, _prices[1] if _prices else {})
    live = _prices[1]
    return [
        e.model_copy(
            update=dict(zip(("prompt_price", "completion_price"), live[e.id], strict=True))
        )
        if e.id in live
        else e
        for e in _load()
    ]
