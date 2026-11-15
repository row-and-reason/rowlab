"""Labels people set: answers to a task, kept in the database, a row per labelled row.

Labels go in the dataset as answer columns named by whoever sets them, e.g. `gold`, with the task they
answer: given with the first labels, so `data` can turn them into typed columns (`datasets.attach`), and
compared with what models answer. People label any rows, at any time, before or after models are asked,
and change or clear a label whenever; who set it, and when, is kept with it.
"""

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rowlab.core import datasets, db, storage, tasks
from rowlab.core.datasets import ROW_ID, AnswerColumn
from rowlab.core.errors import InvalidRequest
from rowlab.core.storage import sql_string
from rowlab.core.tasks import Task


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_id: int = Field(strict=True, ge=0, le=9223372036854775807)
    value: Any = Field(
        description="The label; null clears it. Yes/no takes true or false, pick one and scale an "
        "option's name, pick any a list of names, write text, extract an object keyed by field name."
    )


class SetLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: Task | None = Field(
        None,
        description="The question the labels answer: needed with the first labels in a column, and "
        "otherwise the same as then. Its `column` is the column's name; it asks no models.",
    )
    labels: list[Label] = Field(min_length=1, max_length=1000)


def set_labels(
    dataset_id: str, column: str, request: SetLabels, set_by: str | None
) -> AnswerColumn:
    """Set, change or clear labels in a column. A batch is saved whole or not at all."""
    known = {a.name: a for a in datasets.answer_columns(dataset_id) if a.model is None}
    task = request.task
    if task is None:
        if column not in known:
            raise InvalidRequest(
                f"`{column}` has no labels yet: give the task they answer with the first ones."
            )
        task = known[column].task
    task = task.model_copy(update={"column": column, "models": [], "reason": False})
    tasks.check(task, labels=True)
    datasets.check_answers(dataset_id, task, [None])
    values = {label.row_id: label.value for label in request.labels}
    if len(values) != len(request.labels):
        raise InvalidRequest("Each row may appear only once in a batch.")
    for value in values.values():
        tasks.read_label(task, value)  # Raises InvalidRequest for a value the task can't take.
    _check_rows(dataset_id, list(values))
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        datasets.lock(conn, dataset_id)
        datasets.add_answers(conn, dataset_id, task, None)
        for row_id, value in values.items():
            if value is None:
                conn.execute(
                    "DELETE FROM labels WHERE dataset_id = ? AND name = ? AND row_id = ?",
                    (dataset_id, column, row_id),
                )
                continue
            conn.execute(
                "INSERT INTO labels (dataset_id, name, row_id, value, set_by, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (dataset_id, name, row_id) DO UPDATE SET"
                " value = excluded.value, set_by = excluded.set_by, updated_at = excluded.updated_at",
                (dataset_id, column, row_id, json.dumps(value, ensure_ascii=False), set_by, now),
            )
    return next(
        a for a in datasets.answer_columns(dataset_id) if a.name == column and a.model is None
    )


def _check_rows(dataset_id: str, row_ids: list[int]) -> None:
    data = sql_string(storage.location(dataset_id, "data.parquet"))
    with storage.connect() as con:
        found = con.execute(
            f"SELECT count(*) FROM read_parquet({data}) WHERE {ROW_ID} IN"
            " (SELECT unnest(?::BIGINT[]))",
            [row_ids],
        ).fetchone()[0]
    if found != len(row_ids):
        raise InvalidRequest("Every row must be one of the dataset's.")
