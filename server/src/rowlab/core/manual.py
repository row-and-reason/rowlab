"""Manual runs use the same dataset rows, typed answer parts and final output as model runs."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rowlab.core import datasets, db, runs, storage, tasks
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.storage import sql_string


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_id: int = Field(strict=True, ge=0, le=9223372036854775807)
    value: Any = Field(
        description="The label; null clears it. Pick any takes option names; extract takes an object keyed by field name."
    )


class Answers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[Answer] = Field(min_length=1, max_length=1000)


def save(run_id: str, task_id: str, request: Answers) -> runs.Run:
    """Set current labels. Saves and finishing serialize on the run; a retry sets the same values.

    Only affected parts (at most CHUNK_ROWS source IDs each) are rewritten. A batch crossing parts
    may be partially saved if the process stops: resend it to complete it. No per-label DB rows.
    """
    with db.connect() as conn:
        conn.execute("UPDATE runs SET done = done WHERE id = ?", (run_id,))
        run = runs.get_run(run_id)
        if run.config.method != "manual" or run.status != "manual":
            raise InvalidRequest("This run is not open for manual labeling.")
        task = next((t for t in run.config.tasks if t.id == task_id), None)
        if task is None:
            raise NotFound("Task not found in this run.")
        by_row = {a.row_id: tasks.read_manual(task, a.value) for a in request.answers}
        if len(by_row) != len(request.answers):
            raise InvalidRequest("Each row may appear only once in a batch.")
        with storage.connect() as con:
            found = con.execute(
                f"SELECT count(*) FROM read_parquet({sql_string(storage.location(run.dataset_id, 'asked.parquet'))}) WHERE __row_id IN (SELECT unnest(?::BIGINT[]))",
                [list(by_row)],
            ).fetchone()[0]
        if found != len(by_row):
            raise InvalidRequest("Every row must belong to this run.")
        for chunk in sorted({row_id // runs.CHUNK_ROWS for row_id in by_row}):
            name = f"manual-{chunk}"
            file = storage.location(run.dataset_id, "parts", name + ".parquet")
            current = datasets.read_run_part(run.dataset_id, name) if storage.exists(file) else {}
            for row_id, values in by_row.items():
                if row_id // runs.CHUNK_ROWS == chunk:
                    current[row_id] = current.get(row_id, {}) | values
            datasets.write_run_part(
                run.dataset_id, tasks.part_columns(run.config.tasks, manual=True), name, current
            )
        done = runs.manual_done(run)
        conn.execute(
            "UPDATE runs SET done = ?, updated_at = ? WHERE id = ?",
            (done, datetime.now(UTC).isoformat(), run_id),
        )
    return runs.get_run(run_id)


def finish(run_id: str) -> runs.Run:
    """Freeze the output. Until commit, readers use the parts, so a crash can safely be retried."""
    with db.connect() as conn:
        conn.execute("UPDATE runs SET done = done WHERE id = ?", (run_id,))
        run = runs.get_run(run_id)
        if run.config.method != "manual":
            raise InvalidRequest("Only manual runs need Finish labeling.")
        if run.status == "done":
            return run
        if run.status != "manual":
            raise InvalidRequest("This run is not open for manual labeling.")
        target = storage.location(run.dataset_id, "data.parquet")
        with storage.connect() as con:
            storage.write(
                con,
                f"SELECT * FROM {datasets.dataset_source(run.dataset_id, unfinished=True)} ORDER BY __row_id",
                target,
            )
        conn.execute(
            "UPDATE datasets SET size_bytes = ? WHERE id = ?",
            (storage.size(target), run.dataset_id),
        )
        conn.execute(
            "UPDATE runs SET status = 'done', done = ?, updated_at = ? WHERE id = ?",
            (runs.manual_done(run), datetime.now(UTC).isoformat(), run_id),
        )
    return runs.get_run(run_id)
