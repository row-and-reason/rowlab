"""Jobs: which rows of a dataset to process (the scope), and the tasks to run on each."""

import json
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from rowlab.core import datasets, db, tasks
from rowlab.core.datasets import Scope
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers import openrouter
from rowlab.core.tasks import Task

# A new job runs on a few rows, so its first run is cheap.
DEFAULT_LIMIT = 20


class JobConfig(BaseModel):
    # Responses always include every field, so the API schema marks them required there.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    scope: Scope = Field(default_factory=lambda: Scope(limit=DEFAULT_LIMIT))
    tasks: list[Task] = Field(default_factory=lambda: [Task()])


class Job(JobConfig):
    id: str
    dataset_id: str
    created_at: datetime
    updated_at: datetime


def list_jobs(dataset_id: str) -> list[Job]:
    datasets.get_dataset(dataset_id)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE dataset_id = ? ORDER BY created_at", (dataset_id,)
        ).fetchall()
    return [_from_row(row) for row in rows]


def create_job(dataset_id: str, config: JobConfig) -> Job:
    datasets.get_dataset(dataset_id)
    now = datetime.now(UTC)
    job = Job(
        **config.model_dump(),
        id=uuid.uuid4().hex,
        dataset_id=dataset_id,
        created_at=now,
        updated_at=now,
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, dataset_id, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (job.id, dataset_id, config.model_dump_json(), now.isoformat(), now.isoformat()),
        )
    return job


def get_job(job_id: str) -> Job:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise NotFound(f"Job {job_id} not found")
    return _from_row(row)


def update_job(job_id: str, config: JobConfig) -> Job:
    get_job(job_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET config = ?, updated_at = ? WHERE id = ?",
            (config.model_dump_json(), datetime.now(UTC).isoformat(), job_id),
        )
    return get_job(job_id)


def check(job: Job) -> None:
    """Raise InvalidRequest, naming the task, if the job can't run as configured."""
    if not job.tasks:
        raise InvalidRequest("Add a task.")
    for task in job.tasks:
        try:
            tasks.check(task)
            for model in task.models:
                openrouter.model_kind(model)
        except InvalidRequest as e:
            raise InvalidRequest(f"Task {task.column or 'without a column name'}: {e}") from e
    columns = [c for task in job.tasks for c in tasks.result_columns(task)]
    duplicates = sorted({c for c in columns if columns.count(c) > 1})
    if duplicates:
        raise InvalidRequest(f"Two tasks write the same column: {', '.join(duplicates)}.")
    # E.g. running the same task again on a dataset an earlier run made.
    existing = sorted(set(columns) & {c.name for c in datasets.get_dataset(job.dataset_id).columns})
    if existing:
        raise InvalidRequest(
            f"The dataset already has a column {', '.join(existing)}. Rename the task's result column."
        )


def _from_row(row) -> Job:
    return Job(
        **json.loads(row["config"]),
        id=row["id"],
        dataset_id=row["dataset_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
