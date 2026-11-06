"""Runs: a job executed on the rows in its scope, in the background. Each run keeps a frozen copy of
the job's settings, its progress, its answers per row and what it cost, so earlier runs can be looked
at and compared."""

import json
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from rowlab.core import datasets, db, jobs, prompts, settings, tasks
from rowlab.core.datasets import ROW_ID, Query
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.jobs import JobConfig
from rowlab.core.providers import openrouter
from rowlab.core.tasks import Task

# Model calls made at once during a run.
RUN_CONCURRENCY = 8

# Until answers are stored as they arrive (and runs can resume), runs are kept small.
MAX_RUN_ROWS = 1000

# How often a running run records its progress.
PROGRESS_INTERVAL_SECONDS = 0.5


class RunRow(BaseModel):
    row_id: int
    values: dict[str, Any] = Field(description="Each answer column and its `_proba` column.")
    errors: dict[str, str] = Field(description="Why an answer column is missing, by column.")


class TaskModelCost(BaseModel):
    task_id: str
    model: str
    cost: float = Field(description="USD spent by this run; cached answers are free.")
    failed: int = Field(description="Rows without an answer.")


class RunSummary(BaseModel):
    id: str
    dataset_id: str
    number: int = Field(description="1, 2, … per dataset.")
    status: Literal["running", "done", "failed"]
    done: int = Field(description="Model calls answered so far.")
    total: int = Field(description="Model calls the run makes.")
    error: str | None = Field(description="Why the run failed.")
    config: JobConfig = Field(description="The job's scope and tasks when the run started.")
    columns: list[str] = Field(description="The answer columns, each with a `_proba` column.")
    costs: list[TaskModelCost] = Field(description="Per task and model.")
    row_count: int
    cost: float = Field(description="USD spent by this run; cached answers are free.")
    created_at: datetime


class Run(RunSummary):
    rows: list[RunRow]


class _Answer(BaseModel):
    values: dict[str, Any] = {}
    error: str | None = None
    cost: float = 0
    cached: bool = False


def create_run(job_id: str) -> RunSummary:
    """Start running every task with every model on the rows in the job's scope. The run executes in
    the background; its status and progress show in `get_run` and the dataset list."""
    job = jobs.get_job(job_id)
    jobs.check(job)
    api_key = settings.openrouter_key()
    if api_key is None:
        raise InvalidRequest("Set your OpenRouter API key first.")

    page = datasets.query_dataset(
        job.dataset_id, Query(**job.scope.model_dump(), page_size=MAX_RUN_ROWS)
    )
    if page.total > MAX_RUN_ROWS:
        raise InvalidRequest(
            f"The scope has {page.total:,} rows. Runs are limited to {MAX_RUN_ROWS:,} rows for "
            "now: set a limit."
        )
    config = JobConfig(scope=job.scope, tasks=job.tasks)
    run_id = uuid.uuid4().hex
    total = len(page.rows) * sum(len(task.models) for task in job.tasks)
    with db.connect() as conn:
        number = conn.execute(
            "SELECT coalesce(max(number), 0) + 1 FROM runs WHERE dataset_id = ?", (job.dataset_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO runs (id, dataset_id, number, config, columns, costs, row_count, cost,"
            " created_at, status, done, total) VALUES (?, ?, ?, ?, ?, '[]', ?, 0, ?, 'running', 0, ?)",
            (
                run_id,
                job.dataset_id,
                number,
                config.model_dump_json(),
                json.dumps([c for task in job.tasks for c in tasks.result_columns(task)]),
                len(page.rows),
                datetime.now(UTC).isoformat(),
                total,
            ),
        )
    _start(lambda: _execute(run_id, job.dataset_id, config, page.rows, api_key))
    return get_run(run_id)


def fail_interrupted_runs() -> None:
    """Mark runs that were running when the server stopped as failed. Called on startup."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE runs SET status = 'failed', error = 'The server stopped during the run.'"
            " WHERE status = 'running'"
        )


def _start(work: Callable[[], None]) -> None:
    """Run `work` in a background thread. Tests replace this to run it right away."""
    threading.Thread(target=work, daemon=True).start()


def _execute(
    run_id: str, dataset_id: str, config: JobConfig, rows: list[dict], api_key: str
) -> None:
    """Make every model call, recording progress as they finish, then store the answers."""
    try:
        keys = {path: k for path, (_, k) in datasets.dataset_fields(dataset_id).items()}
        units = [
            (row, task, model) for row in rows for task in config.tasks for model in task.models
        ]

        def ask(unit: tuple[dict, Task, str]) -> _Answer:
            row, task, model = unit
            return _ask(task, model, prompts.render(task.template, row, keys), api_key)

        answers: list[_Answer | None] = [None] * len(units)
        saved_at = time.monotonic()
        with ThreadPoolExecutor(RUN_CONCURRENCY) as pool:
            futures = {pool.submit(ask, unit): i for i, unit in enumerate(units)}
            for done, future in enumerate(as_completed(futures), start=1):
                answers[futures[future]] = future.result()
                # Often enough for a live progress bar, without writing on every call.
                if time.monotonic() - saved_at > PROGRESS_INTERVAL_SECONDS:
                    with db.connect() as conn:
                        conn.execute("UPDATE runs SET done = ? WHERE id = ?", (done, run_id))
                    saved_at = time.monotonic()

        results = {row[ROW_ID]: RunRow(row_id=row[ROW_ID], values={}, errors={}) for row in rows}
        by_task_model: dict[tuple[str, str], list[_Answer]] = {}
        for (row, task, model), answer in zip(units, answers):
            assert answer is not None
            result = results[row[ROW_ID]]
            if answer.error is None:
                result.values |= tasks.with_model(task, model, answer.values)
            else:
                for base in tasks.base_columns(task):
                    result.errors[f"{base}__{tasks.model_slug(model)}"] = answer.error
            by_task_model.setdefault((task.id, model), []).append(answer)

        costs = [
            TaskModelCost(
                task_id=task_id,
                model=model,
                cost=sum(a.cost for a in answered if not a.cached),
                failed=sum(a.error is not None for a in answered),
            )
            for (task_id, model), answered in by_task_model.items()
        ]
        with db.connect() as conn:
            conn.executemany(
                "INSERT INTO run_rows (run_id, row_id, vals, errors) VALUES (?, ?, ?, ?)",
                [
                    (run_id, r.row_id, json.dumps(r.values), json.dumps(r.errors))
                    for r in results.values()
                ],
            )
            conn.execute(
                "UPDATE runs SET status = 'done', done = total, costs = ?, cost = ? WHERE id = ?",
                (json.dumps([c.model_dump() for c in costs]), sum(c.cost for c in costs), run_id),
            )
    except Exception as e:
        with db.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = 'failed', error = ? WHERE id = ?", (str(e), run_id)
            )
        raise


def list_runs(dataset_id: str) -> list[RunSummary]:
    """A dataset's runs, newest first."""
    datasets.get_dataset(dataset_id)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE dataset_id = ? ORDER BY number DESC", (dataset_id,)
        ).fetchall()
    return [_summary(row) for row in rows]


def get_run(run_id: str) -> Run:
    """A run with its answers for every row."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFound(f"Run {run_id} not found")
        answers = conn.execute(
            "SELECT * FROM run_rows WHERE run_id = ? ORDER BY row_id", (run_id,)
        ).fetchall()
    return Run(
        **_summary(row).model_dump(),
        rows=[
            RunRow(row_id=a["row_id"], values=json.loads(a["vals"]), errors=json.loads(a["errors"]))
            for a in answers
        ],
    )


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


def _summary(row) -> RunSummary:
    return RunSummary(
        id=row["id"],
        dataset_id=row["dataset_id"],
        number=row["number"],
        config=json.loads(row["config"]),
        columns=json.loads(row["columns"]),
        costs=json.loads(row["costs"]),
        row_count=row["row_count"],
        cost=row["cost"],
        created_at=row["created_at"],
        status=row["status"],
        done=row["done"],
        total=row["total"],
        error=row["error"],
    )
