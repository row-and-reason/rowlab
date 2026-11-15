from typing import Annotated

from fastapi import APIRouter, Query

from rowlab.api.auth import CanRead
from rowlab.core import catalog, tasks
from rowlab.core.tasks import TaskTypes

router = APIRouter(prefix="/v1/utils", tags=["utils"])


@router.get("/models", operation_id="listModels")
def list_models(
    me: CanRead,
    everything: Annotated[
        bool,
        Query(
            alias="all",
            description="Also the rest of OpenRouter's catalog, after rowlab's list, by id.",
        ),
    ] = False,
) -> list[catalog.Model]:
    """The models a task can use, decision models and LLMs, with current prices: rowlab's list, in
    the order we'd pick them; with `all`, every model in OpenRouter's catalog rowlab can ask."""
    return catalog.models(everything=everything)


@router.get("/task-types", operation_id="getTaskTypes")
def task_types(me: CanRead) -> TaskTypes:
    """The answer types a task can have (classify, extract, write), starting points for write tasks,
    and the types an extracted field can have."""
    return tasks.task_types()
