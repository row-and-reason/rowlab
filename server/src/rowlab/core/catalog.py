"""The models rowlab can ask. Its own list (`models.toml`) is its opinion: a picked set, in the order
we'd pick them, with tags, offered first. Any other model in OpenRouter's public catalog can be asked
too, by id. OpenRouter's catalog is fetched hourly, for its models and everyone's current prices; when
it can't be reached, the list's own prices are used and only listed models are known.
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
CATALOG_TTL_SECONDS = 3600
# After OpenRouter fails to answer, its catalog is asked for again after this long.
CATALOG_RETRY_SECONDS = 60


class Model(BaseModel):
    id: str
    name: str
    kind: Literal["decision", "llm"]
    tags: list[str] = Field(
        description="`recommended` for the ones to try first; others (`budget`, `accurate`) to filter by."
    )
    listed: bool = Field(
        description="On rowlab's own list, offered first. The rest of OpenRouter's catalog can be "
        "asked too."
    )
    prompt_price: float = Field(description="USD per input token.")
    completion_price: float = Field(description="USD per output token.")
    context_length: int


_list: list[Model] | None = None
_openrouter: tuple[float, dict[str, Model]] | None = None


def models(*, everything: bool = False) -> list[Model]:
    """The listed models, in the list's order, at current prices; with `everything`, the rest of
    OpenRouter's catalog after them, by id."""
    live = _catalog()
    listed = [_priced(m, live) for m in _load()]
    if not everything:
        return listed
    ids = {m.id for m in listed}
    return listed + sorted((m for m in live.values() if m.id not in ids), key=lambda m: m.id)


def get(model_id: str) -> Model:
    """A model by id, with its prices: listed, or in OpenRouter's catalog."""
    live = _catalog()
    for model in _load():
        if model.id == model_id:
            return _priced(model, live)
    if model_id in live:
        return live[model_id]
    if not live:
        raise InvalidRequest(
            f"Couldn't check {model_id} with OpenRouter's catalog. Try again, or pick a model from "
            "rowlab's list."
        )
    raise InvalidRequest(
        f"Unknown model: {model_id}. Use a decision model, or an LLM with structured outputs, from "
        "OpenRouter's catalog."
    )


def kind(model_id: str) -> Literal["decision", "llm"]:
    """Whether a model is a decision model or an LLM. Runs call this per row: the list, else
    OpenRouter's catalog as last fetched (asked for at most hourly)."""
    for model in _load():
        if model.id == model_id:
            return model.kind
    return get(model_id).kind


class ModelPage(BaseModel):
    models: list[Model]
    total: int
    next_offset: int | None


def list_models(
    search: str = "",
    kind: Literal["decision", "llm"] | None = None,
    tag: str | None = None,
    everything: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> ModelPage:
    needle = search.lower()
    found = [
        m
        for m in models(everything=everything)
        if (kind is None or m.kind == kind)
        and (tag is None or tag in m.tags)
        and (needle in m.id.lower() or needle in m.name.lower())
    ]
    return ModelPage(
        models=found[offset : offset + limit],
        total=len(found),
        next_offset=offset + limit if offset + limit < len(found) else None,
    )


def _load() -> list[Model]:
    global _list
    if _list is None:
        with FILE.open("rb") as f:
            _list = [
                Model(
                    id=m["id"],
                    name=m["name"],
                    kind=m["kind"],
                    tags=m.get("tags", []),
                    listed=True,
                    prompt_price=m.get("price_in", 0) / 1e6,
                    completion_price=m.get("price_out", 0) / 1e6,
                    context_length=m.get("context_length", 0),
                )
                for m in tomllib.load(f)["models"]
            ]
    return _list


def _catalog() -> dict[str, Model]:
    """OpenRouter's catalog by id, as last fetched; empty if it never answered."""
    global _openrouter
    if _openrouter is None or time.monotonic() > _openrouter[0]:
        try:
            fetched = {m["id"]: Model(**m, tags=[], listed=False) for m in openrouter.models()}
            _openrouter = (time.monotonic() + CATALOG_TTL_SECONDS, fetched)
        # Unreachable, or answering in a shape it didn't before: what it said last will do.
        except (ProviderError, KeyError, TypeError, ValueError) as e:
            log.warning("Using the model list's own prices: %s", e)
            last = _openrouter[1] if _openrouter else {}
            _openrouter = (time.monotonic() + CATALOG_RETRY_SECONDS, last)
    return _openrouter[1]


def _priced(model: Model, live: dict[str, Model]) -> Model:
    """A listed model, at OpenRouter's current prices when it has them."""
    if model.id not in live:
        return model
    found = live[model.id]
    return model.model_copy(
        update={"prompt_price": found.prompt_price, "completion_price": found.completion_price}
    )
