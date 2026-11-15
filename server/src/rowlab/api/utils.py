from fastapi import APIRouter

from rowlab.api.auth import CanRead
from rowlab.core import catalog, tasks
from rowlab.core.tasks import TaskTypes

router = APIRouter(prefix="/v1/utils", tags=["utils"])


@router.get("/models", operation_id="listModels")
def list_models(me: CanRead) -> list[catalog.Model]:
    """The models a task can use, decision models and LLMs, in the order we'd pick them, with
    current prices."""
    return catalog.models()


@router.get("/task-types", operation_id="getTaskTypes")
def task_types(me: CanRead) -> TaskTypes:
    """The answer types a task can have (classify, extract, write), starting points for write tasks,
    and the types an extracted field can have."""
    return tasks.task_types()
