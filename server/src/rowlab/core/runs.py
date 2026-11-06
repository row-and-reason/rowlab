"""Runs: a job executed on the rows in its scope, making a new dataset, by one runner thread.

Starting a run copies every row of the dataset into a new one, which shows up straight away; the rows
in the job's scope get their answers as the run goes, the others keep empty answer columns. The run keeps
a frozen copy of the job's settings. The runner processes queued runs oldest first, one at a time, in
chunks of the rows in scope by `__row_id` (chunk k is always the same rows). A chunk's answers are written to the dataset's `parts/part-{k}.parquet` in one go, and only then
does the run's bookmark (`next_chunk`) move on. So a stop, a crash or a restart loses at most the chunk
in progress, and redoing it costs nothing: answers come from the response cache. When every chunk is
written, the dataset is written out as one Parquet file.
"""

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import datasets, db, jobs, prompts, settings, tasks
from rowlab.core.datasets import ROW_ID
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.jobs import JobConfig
from rowlab.core.providers import openrouter
from rowlab.core.tasks import Task

# Rows per chunk: the most work a stop or crash can lose (and redo for free).
CHUNK_ROWS = 500

# Model calls made at once.
CONCURRENCY = 16

# How often a run's progress is saved, and how often the runner checks for a stop.
PROGRESS_INTERVAL_SECONDS = 0.5

log = logging.getLogger(__name__)

Status = Literal["queued", "running", "stopping", "stopped", "done", "failed"]


class TaskModelCost(BaseModel):
    task_id: str
    model: str
    cost: float = Field(description="USD spent by this run; cached answers are free.")
    failed: int = Field(description="Rows without an answer.")


class Run(BaseModel):
    id: str
    dataset_id: str = Field(description="The dataset it makes.")
    number: int = Field(description="1, 2, … per parent dataset.")
    status: Status
    config: JobConfig = Field(description="The job's scope and tasks when the run started.")
    columns: list[str] = Field(description="The answer columns, each with a `_proba` column.")
    costs: list[TaskModelCost] = Field(description="Per task and model, so far.")
    row_count: int = Field(description="Rows it asks about: the rows in its scope.")
    next_chunk: int = Field(description="The first chunk of rows not yet written.")
    done: int = Field(description="Model calls answered (or failed) so far.")
    total: int = Field(description="Model calls the run makes.")
    cost: float = Field(description="USD spent so far; cached answers are free.")
    error: str | None = Field(description="Why the run failed.")
    created_at: datetime
    updated_at: datetime | None


class _Answer(BaseModel):
    values: dict[str, Any] = {}
    error: str | None = None
    cost: float = 0
    cached: bool = False


_wake = threading.Event()


def create_run(job_id: str) -> Run:
    """Queue a run of every task with every model on the rows in the job's scope. Its dataset, with
    every row of the job's dataset and empty answer columns, is created right away."""
    job = jobs.get_job(job_id)
    jobs.check(job)
    if settings.openrouter_key() is None:
        raise InvalidRequest("Set your OpenRouter API key first.")

    with db.connect() as conn:
        number = conn.execute(
            "SELECT coalesce(max(r.number), 0) + 1 FROM runs r"
            " JOIN datasets d ON d.id = r.dataset_id WHERE d.parent_id = ?",
            (job.dataset_id,),
        ).fetchone()[0]
    dataset_id, asked = datasets.write_run_rows(job.dataset_id, job.scope)
    try:
        if asked == 0:
            raise InvalidRequest("The scope has no rows.")
        # An empty part gives the answer columns their types before any chunk is written.
        _write_part(dataset_id, job.tasks, "part-schema", {})
        datasets.register_run_dataset(dataset_id, job.dataset_id, number)
        run_id = uuid.uuid4().hex
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, dataset_id, number, status, config, columns, costs,"
                " row_count, total, created_at) VALUES (?, ?, ?, 'queued', ?, ?, '[]', ?, ?, ?)",
                (
                    run_id,
                    dataset_id,
                    number,
                    JobConfig(scope=job.scope, tasks=job.tasks).model_dump_json(),
                    json.dumps([c for task in job.tasks for c in tasks.result_columns(task)]),
                    asked,
                    asked * sum(len(task.models) for task in job.tasks),
                    datetime.now(UTC).isoformat(),
                ),
            )
    except BaseException:
        with db.connect() as conn:
            conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        datasets.delete_files(dataset_id)
        raise
    _wake.set()
    return get_run(run_id)


def get_run(run_id: str) -> Run:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"Run {run_id} not found")
    return _from_row(row)


def stop_run(run_id: str) -> Run:
    """Stop after the calls in flight; a queued run stops right away. Resume continues it."""
    run = get_run(run_id)
    status = {"queued": "stopped", "running": "stopping"}.get(run.status)
    if status is None:
        raise InvalidRequest(f"Run #{run.number} is {run.status}, not running.")
    _set(run_id, status=status)
    return get_run(run_id)


def resume_run(run_id: str) -> Run:
    """Queue a stopped or failed run again; it continues from its first unwritten chunk."""
    run = get_run(run_id)
    if run.status not in ("stopped", "failed"):
        raise InvalidRequest(f"Run #{run.number} is {run.status}, not stopped.")
    _set(run_id, status="queued", error=None)
    _wake.set()
    return get_run(run_id)


def start_runner() -> None:
    """Start the runner thread, called once when the server starts."""
    recover_interrupted_runs()
    threading.Thread(target=_runner, name="rowlab-runner", daemon=True).start()


def recover_interrupted_runs() -> None:
    """Queue runs that the last stop of the server cut off; they continue where they were."""
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'queued' WHERE status = 'running'")
        conn.execute("UPDATE runs SET status = 'stopped' WHERE status = 'stopping'")


def process_next() -> bool:
    """Process the oldest queued run, if there is one. Returns whether there was."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
    if row is None:
        return False
    _process(row["id"])
    return True


def _runner() -> None:
    while True:
        try:
            if process_next():
                continue
        except Exception:
            # The run is marked failed with its error; log it and keep serving the others.
            log.exception("Run failed")
        _wake.wait(timeout=5)
        _wake.clear()


def _process(run_id: str) -> None:
    run = get_run(run_id)
    _set(run_id, status="running")
    try:
        api_key = settings.openrouter_key()
        if api_key is None:
            raise InvalidRequest("Set your OpenRouter API key first.")
        keys = {path: k for path, (_, k) in datasets.dataset_fields(run.dataset_id).items()}
        chunks = -(-run.row_count // CHUNK_ROWS)
        for chunk in range(run.next_chunk, chunks):
            if not _process_chunk(run, chunk, keys, api_key):
                _set(run_id, status="stopped")
                return
            run = get_run(run_id)
        datasets.finish_run_dataset(run.dataset_id)
        _set(run_id, status="done")
    except Exception as e:
        _set(run_id, status="failed", error=str(e))
        raise


def _process_chunk(run: Run, chunk: int, keys: dict[str, list[str]], api_key: str) -> bool:
    """Ask every task and model for the chunk's rows and write its part file. Returns False, writing
    nothing, if the run was stopped meanwhile."""
    rows = datasets.read_run_rows(run.dataset_id, offset=chunk * CHUNK_ROWS, limit=CHUNK_ROWS)
    # Calls in the chunks already written; a chunk being redone after a stop counts from zero.
    per_row = sum(len(task.models) for task in run.config.tasks)
    done_before = chunk * CHUNK_ROWS * per_row
    units = [
        (row, task, model) for row in rows for task in run.config.tasks for model in task.models
    ]
    stopping = threading.Event()
    answers: list[_Answer | None] = [None] * len(units)

    def ask(i: int) -> None:
        if stopping.is_set():
            return
        row, task, model = units[i]
        answers[i] = _ask(task, model, prompts.render(task.template, row, keys), api_key)

    with ThreadPoolExecutor(CONCURRENCY) as pool:
        futures = [pool.submit(ask, i) for i in range(len(units))]
        while not all(f.done() for f in futures):
            time.sleep(PROGRESS_INTERVAL_SECONDS)
            finished = sum(a is not None for a in answers)
            _set(run.id, done=done_before + finished)
            # A deleted dataset takes its run with it.
            if _status(run.id) in ("stopping", None):
                stopping.set()
        for future in futures:
            future.result()
    if stopping.is_set():
        return False

    by_row: dict[int, dict[str, Any]] = {row[ROW_ID]: {} for row in rows}
    for (row, task, model), answer in zip(units, answers):
        assert answer is not None
        if answer.error is None:
            by_row[row[ROW_ID]] |= tasks.with_model(task, model, answer.values)
    _write_part(run.dataset_id, run.config.tasks, f"part-{chunk:06d}", by_row)
    costs = {(c.task_id, c.model): c for c in run.costs}
    for (_, task, model), answer in zip(units, answers):
        assert answer is not None
        cost = costs.setdefault(
            (task.id, model), TaskModelCost(task_id=task.id, model=model, cost=0, failed=0)
        )
        cost.cost += 0 if answer.cached else answer.cost
        cost.failed += answer.error is not None
    _set(
        run.id,
        next_chunk=chunk + 1,
        done=done_before + len(units),
        costs=json.dumps([c.model_dump() for c in costs.values()]),
        cost=sum(c.cost for c in costs.values()),
    )
    return True


def _write_part(
    dataset_id: str, run_tasks: list[Task], name: str, by_row: dict[int, dict[str, Any]]
) -> None:
    """Write answers as one Parquet file: `__row_id`, and every answer column with its `_proba`
    (empty where the model failed). Written to a temporary name first, so a part is complete or
    absent."""
    types = {
        column: "BOOLEAN" if task.type in ("yes_no", "pick_any") else "VARCHAR"
        for task in run_tasks
        for column in tasks.result_columns(task)
    }
    columns = [
        (name_, type_)
        for column, value_type in types.items()
        for name_, type_ in [(column, value_type), (f"{column}_proba", "DOUBLE")]
    ]
    path = datasets.run_parts_dir(dataset_id) / f"{name}.parquet"
    temporary = path.with_suffix(".tmp")
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE part ("
            + ", ".join(
                [f"{datasets.sql_ident(ROW_ID)} BIGINT"]
                + [f"{datasets.sql_ident(n)} {t}" for n, t in columns]
            )
            + ")"
        )
        if by_row:
            con.executemany(
                f"INSERT INTO part VALUES ({', '.join('?' for _ in range(len(columns) + 1))})",
                [
                    [row_id, *(values.get(n) for n, _ in columns)]
                    for row_id, values in by_row.items()
                ],
            )
        con.execute(f"COPY part TO {datasets.sql_string(temporary)} (FORMAT parquet)")
    os.replace(temporary, path)


def _ask(task: Task, model: str, prompt: str, api_key: str) -> _Answer:
    """One task for one row from one model, as base columns."""
    decision = openrouter.model_kind(model) == "decision"
    try:
        if decision:
            questions = tasks.decision_questions(task)
            response = openrouter.decide(model, prompt, questions, api_key=api_key)
        else:
            messages = tasks.llm_messages(task, prompt)
            response = openrouter.complete(model, messages, tasks.llm_schema(task), api_key=api_key)
    except openrouter.OpenRouterError as e:
        return _Answer(error=str(e))
    # Paid for even when the reply turns out unusable.
    answer = _Answer(cost=response.cost, cached=response.cached)
    try:
        if decision:
            answer.values = tasks.read_decision(task, response.data)
        else:
            answer.values = tasks.read_llm(task, response.data)
    except tasks.AnswerFormatError as e:
        answer.error = str(e)
    return answer


def _status(run_id: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    return row and row["status"]


def _set(run_id: str, **fields: Any) -> None:
    fields["updated_at"] = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        conn.execute(
            f"UPDATE runs SET {', '.join(f'{name} = ?' for name in fields)} WHERE id = ?",
            [*fields.values(), run_id],
        )


def _from_row(row) -> Run:
    return Run(
        id=row["id"],
        dataset_id=row["dataset_id"],
        number=row["number"],
        status=row["status"],
        config=json.loads(row["config"]),
        columns=json.loads(row["columns"]),
        costs=json.loads(row["costs"]),
        row_count=row["row_count"],
        next_chunk=row["next_chunk"],
        done=row["done"],
        total=row["total"],
        cost=row["cost"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
