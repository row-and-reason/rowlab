from fastapi import APIRouter

from rowlab.api.auth import CanRead
from rowlab.core import tasks
from rowlab.core.providers import openrouter
from rowlab.core.tasks import TaskTypes

router = APIRouter(prefix="/v1/utils", tags=["utils"])


@router.get("/models", operation_id="listModels")
def list_models(me: CanRead) -> list[openrouter.Model]:
    """Models a task can use: decision models, then LLMs with structured outputs, each cheapest
    first."""
    return openrouter.models()


@router.get("/task-types", operation_id="getTaskTypes")
def task_types(me: CanRead) -> TaskTypes:
    """The answer types a task can have (classify, extract, write), starting points for write tasks,
    and the types an extracted field can have."""
    return tasks.task_types()
