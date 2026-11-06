from fastapi import APIRouter

from rowlab.core import tasks
from rowlab.core.tasks import TaskTypes

router = APIRouter(tags=["tasks"])


@router.get("/v1/task-types", operation_id="getTaskTypes")
def task_types() -> TaskTypes:
    """The answer types a task can have (classify, extract, write), starting points for write tasks,
    and the types an extracted field can have."""
    return tasks.task_types()
