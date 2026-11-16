from typing import Annotated

from fastapi import APIRouter, Query

from rowlab.api.auth import CanEdit, CanRead
from rowlab.core import models
from rowlab.core.catalog import Model
from rowlab.core.models import ModelChange, ModelInput

router = APIRouter(prefix="/v1/models", tags=["models"])


@router.get("", operation_id="listModels")
def list_models(
    me: CanRead,
    everything: Annotated[
        bool,
        Query(
            alias="all",
            description="Also the rest of OpenRouter's catalog, after rowlab's list, by id.",
        ),
    ] = False,
) -> list[Model]:
    """The models a task can use, decision models and LLMs: the organisation's own, by id, then
    rowlab's list at current prices, in the order we'd pick them; with `all`, every model in
    OpenRouter's catalog rowlab can ask."""
    return models.listing(me.org.id, everything=everything)


@router.post("", operation_id="createModel", status_code=201)
def create_model(data: ModelInput, me: CanEdit) -> Model:
    """Add a model of the organisation's own, asked through one of its providers: e.g. one served
    with vLLM on a GPU, or a fine-tuned checkpoint. It is asked a short question first, and added
    once it answers. Adding the same model (provider, upstream name and kind) again returns it, or
    brings it back if it was deleted; another model under an id in use, or used before, is
    refused."""
    return models.add(me.org.id, data, me.user.id if me.user else None)


@router.patch("/{model_id}", operation_id="updateModel")
def update_model(model_id: str, data: ModelChange, me: CanEdit) -> Model:
    """Change a model's note or prices. What answers (its provider, upstream name and kind) can't
    change: add a new model for that."""
    return models.update(me.org.id, model_id, data)


@router.delete("/{model_id}", operation_id="deleteModel", status_code=204)
def delete_model(model_id: str, me: CanEdit) -> None:
    """Delete a model of the organisation's own. Its answers stay, and its id goes to no other
    model; adding the same model again brings it back."""
    models.delete(me.org.id, model_id)
