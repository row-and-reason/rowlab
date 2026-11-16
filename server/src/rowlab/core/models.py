"""The models an organisation can ask: its own, then rowlab's catalog (`catalog`).

An organisation adds its own models: open-weight models it serves itself, say, or the checkpoints of
one it fine-tunes. Each is asked through one of its providers, by the name that provider gives it
(`upstream`), and lands in answer columns, comparisons and runs under its id, like a catalog model.
Adding one asks it a short question, so a model that doesn't answer isn't added.

What answers stays fixed: a model's provider, upstream name and kind never change, and a deleted
model's id never goes to another model, because answer columns and the replies kept for them go by
it (adding the same model again brings it back). Its note and prices can change. Ids have no `/`, so
none is ever a catalog id; a model's name is its id. Any member can add models; only admins manage
the providers they go through.
"""

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from rowlab.core import catalog, db, model_providers, tasks
from rowlab.core.catalog import Model, ModelPage
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers.model_api import ProviderError

ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

# What a new model is asked, to check it answers: once, and not for long, as a server still loading
# a model would keep the request waiting for minutes.
_CHECK = tasks.Task(template="Is the sky blue on a clear day?", type="yes_no", column="answer")
_CHECK_SECONDS = 20


class ModelInput(BaseModel):
    id: str = Field(
        description="rowlab's id for it, as answer columns and comparisons show it: lowercase "
        "letters, digits, `.`, `_` and `-`, e.g. `fallacy-ft-step-2000`. Never given to another "
        "model, even once deleted."
    )
    provider: str = Field(description="The provider it is asked through, by name or id.")
    upstream: str = Field(
        "",
        description="What the provider calls it, e.g. the name vLLM serves it under. Defaults to "
        "the id.",
    )
    kind: Literal["decision", "llm"] = Field(
        "decision", description="A decision model, or an LLM with structured outputs."
    )
    note: str = Field(
        "",
        description="What answers, to read in results later: e.g. the base model and revision, "
        "the checkpoint's step and training run.",
    )
    prompt_price: float | None = Field(None, ge=0, description="USD per input token, if known.")
    completion_price: float | None = Field(
        None, ge=0, description="USD per output token, if known."
    )


class ModelChange(BaseModel):
    """What can change about a model; fields left out stay as they are."""

    note: str | None = None
    prompt_price: float | None = Field(None, ge=0)
    completion_price: float | None = Field(None, ge=0)


def listing(org_id: str, *, everything: bool = False) -> list[Model]:
    """The organisation's own models, by id, then rowlab's list (`catalog.models`)."""
    return _own(org_id) + catalog.models(everything=everything)


def page(
    org_id: str,
    search: str = "",
    kind: Literal["decision", "llm"] | None = None,
    tag: str | None = None,
    everything: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> ModelPage:
    """A page of `listing`, filtered by part of an id or name, a kind and a tag."""
    needle = search.lower()
    found = [
        m
        for m in listing(org_id, everything=everything)
        if (kind is None or m.kind == kind)
        and (tag is None or tag in m.tags)
        and (needle in m.id.lower() or needle in m.name.lower())
    ]
    return ModelPage(
        models=found[offset : offset + limit],
        total=len(found),
        next_offset=offset + limit if offset + limit < len(found) else None,
    )


def get(org_id: str, model_id: str) -> Model:
    """A model by id: the organisation's own, or one in rowlab's catalog."""
    if "/" in model_id:
        return catalog.get(model_id)
    row = _row(org_id, model_id)
    if row is None:
        raise InvalidRequest(
            f"Unknown model: {model_id}. Add it as one of your own, or use one from rowlab's list "
            "or OpenRouter's catalog, e.g. `typesafe/jev-1.14`."
        )
    if row["deleted_at"]:
        raise InvalidRequest(f"{model_id} was deleted.")
    return _from_row(row)


def add(org_id: str, data: ModelInput, created_by: str | None) -> Model:
    """Add a model once it answers a short question through its provider. Adding the same model (the
    same provider, upstream name and kind) again returns it, or brings it back if it was deleted;
    another model under its id is refused."""
    if not ID.fullmatch(data.id):
        raise InvalidRequest(
            "A model's id is lowercase letters, digits, `.`, `_` and `-`, up to 64, e.g. "
            "`fallacy-ft-step-2000`."
        )
    provider = model_providers.find(org_id, data.provider)
    model = Model(
        id=data.id,
        name=data.id,
        kind=data.kind,
        tags=[],
        listed=False,
        prompt_price=data.prompt_price,
        completion_price=data.completion_price,
        context_length=0,
        provider_id=provider.id,
        upstream=data.upstream.strip() or data.id,
        note=data.note.strip(),
    )
    saved = _row(org_id, data.id)
    if saved is not None:
        differ = [
            label
            for label, field in (
                ("provider", "provider_id"),
                ("served name", "upstream"),
                ("kind", "kind"),
            )
            if saved[field] != getattr(model, field)
        ]
        if differ:
            was = "was a model here before" if saved["deleted_at"] else "is another model"
            raise InvalidRequest(
                f"{data.id} {was}, with another {' and '.join(differ)}, and answers go by its id. "
                "Pick another id."
            )
        if not saved["deleted_at"]:
            return _from_row(saved)
    _check(org_id, model, provider.name)
    with db.connect() as conn:
        if saved is not None:
            conn.execute(
                "UPDATE models SET deleted_at = NULL, note = ?, prompt_price = ?,"
                " completion_price = ? WHERE org_id = ? AND id = ?",
                (model.note, model.prompt_price, model.completion_price, org_id, model.id),
            )
        else:
            conn.execute(
                "INSERT INTO models (org_id, id, kind, provider_id, upstream, note, prompt_price,"
                " completion_price, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    org_id,
                    model.id,
                    model.kind,
                    model.provider_id,
                    model.upstream,
                    model.note,
                    model.prompt_price,
                    model.completion_price,
                    created_by,
                    datetime.now(UTC).isoformat(),
                ),
            )
    return model


def update(org_id: str, model_id: str, data: ModelChange) -> Model:
    """Change a model's note or prices. What answers can't change: add a new model for that."""
    _own_id(org_id, model_id)
    changes = data.model_dump(exclude_unset=True)
    if "note" in changes:
        changes["note"] = (changes["note"] or "").strip()
    if changes:
        with db.connect() as conn:
            conn.execute(
                f"UPDATE models SET {', '.join(f'{k} = ?' for k in changes)}"
                " WHERE org_id = ? AND id = ?",
                (*changes.values(), org_id, model_id),
            )
    return get(org_id, model_id)


def delete(org_id: str, model_id: str) -> None:
    """Delete a model: new runs can't ask it, and its id goes to no other model. Its answers stay."""
    _own_id(org_id, model_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE models SET deleted_at = ? WHERE org_id = ? AND id = ? AND deleted_at IS NULL",
            (datetime.now(UTC).isoformat(), org_id, model_id),
        )


def _check(org_id: str, model: Model, provider_name: str) -> None:
    """Raise InvalidRequest unless the model answers through its provider in a shape rowlab reads."""
    use = model_providers.for_run(org_id, model.provider_id)
    request = model_providers.request(use.type, _CHECK, model, _CHECK.template)
    try:
        reply = model_providers.ask(use, request, model, attempts=1, timeout=_CHECK_SECONDS)
        if reply.data is None:
            raise tasks.AnswerFormatError("its reply couldn't be read")
        if model.kind == "decision":
            tasks.read_decision(_CHECK, reply.data)
        else:
            tasks.read_llm(_CHECK, reply.data)
    except ProviderError as e:
        hint = (
            "Is the server up, and done loading the model?"
            if e.status is None
            else "Check the name it's served under, and that the provider's type matches the API "
            "the server speaks."
        )
        raise InvalidRequest(
            f"{model.upstream} didn't answer through {provider_name}: {e}. {hint}"
        ) from e
    except tasks.AnswerFormatError as e:
        raise InvalidRequest(
            f"{model.upstream} answered through {provider_name}, but not as rowlab reads it: {e}. "
            "Check that the provider's type matches the API the server speaks."
        ) from e


def _own(org_id: str) -> list[Model]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM models WHERE org_id = ? AND deleted_at IS NULL ORDER BY id", (org_id,)
        ).fetchall()
    return [_from_row(row) for row in rows]


def _own_id(org_id: str, model_id: str) -> None:
    """Raise NotFound unless `model_id` is one of the organisation's own models."""
    row = _row(org_id, model_id)
    if row is None or row["deleted_at"]:
        raise NotFound(f"Model {model_id} not found")


def _row(org_id: str, model_id: str):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM models WHERE org_id = ? AND id = ?", (org_id, model_id)
        ).fetchone()


def _from_row(row) -> Model:
    return Model(
        id=row["id"],
        name=row["id"],
        kind=row["kind"],
        tags=[],
        listed=False,
        prompt_price=row["prompt_price"],
        completion_price=row["completion_price"],
        context_length=0,
        provider_id=row["provider_id"],
        upstream=row["upstream"],
        note=row["note"],
    )
