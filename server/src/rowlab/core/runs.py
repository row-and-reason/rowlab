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
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from rowlab.core import datasets, db, prompts, settings, sql, storage, tasks
from rowlab.core.config import config
from rowlab.core.datasets import ROW_ID
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers import openrouter
from rowlab.core.tasks import Task

# Rows per chunk: the most work a stop or crash can lose (and redo for free).
CHUNK_ROWS = 500

# Model calls made at once.
CONCURRENCY = 16

# How often a run's progress is saved, and how often the runner checks for a stop.
PROGRESS_INTERVAL_SECONDS = 0.5

# A run whose progress hasn't been saved for this long has lost its runner, and is queued again.
STALE_SECONDS = 120

log = logging.getLogger(__name__)

Status = Literal["queued", "running", "stopping", "stopped", "done", "failed"]

# Statuses of a run that still has work to do.
ACTIVE = ("queued", "running", "stopping")


class TaskModelCost(BaseModel):
    task_id: str
    model: str
    cost: float = Field(description="USD spent by this run; cached answers are free.")
    failed: int = Field(description="Rows without an answer.")


class RunRequest(BaseModel):
    """What to run: the tasks, on the rows a query picks."""

    sql: str = Field(
        sql.ALL_ROWS,
        description="Which rows to ask about: a SELECT over `data` returning `__row_id`; all rows "
        "by default.",
    )
    tasks: list[Task]


class Run(BaseModel):
    id: str
    dataset_id: str = Field(description="The dataset it makes.")
    status: Status
    config: RunRequest = Field(description="The query and tasks it was started with.")
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


class Estimate(BaseModel):
    rows: int = Field(description="Rows the run would ask about.")
    calls: int = Field(description="Model calls it would make.")
    cost: float = Field(
        description="Roughly what it would cost in USD, from sample rows' token counts and the models' "
        "prices; answers already in the response cache would be free."
    )
    problem: str | None = Field(description="Why it can't run as it is, and what to change.")


class _Answer(BaseModel):
    values: dict[str, Any] = {}
    error: str | None = None
    cost: float = 0
    cached: bool = False


_wake = threading.Event()


def create_run(dataset_id: str, request: RunRequest) -> Run:
    """Queue a run of every task with every model on the rows the query picks. Its dataset, with
    every row of the dataset and empty answer columns, is created right away."""
    check(dataset_id, request)
    if settings.openrouter_key(datasets.org_of(dataset_id)) is None:
        raise InvalidRequest("Set your OpenRouter API key first.")
    with sql.connect(dataset_id) as con:
        query = sql.row_ids(con, request.sql)
        asked = [r[0] for r in sql.execute(con, f"{query} ORDER BY {ROW_ID}").fetchall()]
    if not asked:
        raise InvalidRequest("The query picks no rows.")

    made_id = datasets.write_run_rows(dataset_id, asked)
    try:
        # An empty part gives the answer columns their types before any chunk is written.
        _write_part(made_id, request.tasks, "part-schema", {})
        datasets.register_run_dataset(made_id, dataset_id)
        run_id = uuid.uuid4().hex
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, dataset_id, status, config, columns, costs,"
                " row_count, total, created_at) VALUES (?, ?, 'queued', ?, ?, '[]', ?, ?, ?)",
                (
                    run_id,
                    made_id,
                    request.model_dump_json(),
                    json.dumps([c for task in request.tasks for c in tasks.result_columns(task)]),
                    len(asked),
                    len(asked) * sum(len(task.models) for task in request.tasks),
                    datetime.now(UTC).isoformat(),
                ),
            )
    except BaseException:
        with db.connect() as conn:
            conn.execute("DELETE FROM datasets WHERE id = ?", (made_id,))
        storage.delete_dataset(made_id)
        raise
    _wake.set()
    return get_run(run_id)


def check(dataset_id: str, request: RunRequest) -> None:
    """Raise InvalidRequest, naming the task, if the run can't go as configured."""
    if not request.tasks:
        raise InvalidRequest("Add a task.")
    for task in request.tasks:
        try:
            tasks.check(task)
            for model in task.models:
                kind = openrouter.model_kind(model)
                if kind == "decision" and task.type in tasks.LLM_ONLY:
                    raise InvalidRequest(
                        f"{task.type.title()} needs an LLM: {tasks.model_slug(model)} is a "
                        "decision model."
                    )
                if kind == "decision" and task.reason:
                    raise InvalidRequest(
                        f"Only LLMs give a reason: {tasks.model_slug(model)} is a decision model."
                    )
        except InvalidRequest as e:
            raise InvalidRequest(f"Task {task.column or 'without a column name'}: {e}") from e
    columns = [c for task in request.tasks for c in tasks.result_columns(task)]
    duplicates = sorted({c for c in columns if columns.count(c) > 1})
    if duplicates:
        raise InvalidRequest(f"Two tasks write the same column: {', '.join(duplicates)}.")
    # E.g. running the same task again on a dataset an earlier run made.
    existing = sorted(set(columns) & {c.name for c in datasets.get_dataset(dataset_id).columns})
    if existing:
        raise InvalidRequest(
            f"The dataset already has a column {', '.join(existing)}. Rename the task's result column."
        )


# Rows sampled to estimate prompt sizes, and roughly how many tokens answers take.
ESTIMATE_SAMPLE_ROWS = 20
_ANSWER_TOKENS = {"classify": 20, "field": 15, "reason": 60}


def estimate(dataset_id: str, request: RunRequest) -> Estimate:
    """How many rows and model calls a run would take, and roughly what it would cost."""
    try:
        total = sql.count(dataset_id, request.sql)
        rows = sql.query(
            dataset_id, sql.QueryRequest(sql=request.sql, limit=ESTIMATE_SAMPLE_ROWS)
        ).rows
    except InvalidRequest as e:
        return Estimate(rows=0, calls=0, cost=0, problem=str(e))
    calls = total * sum(len(task.models) for task in request.tasks)
    problem = None
    try:
        check(dataset_id, request)
        if total == 0:
            raise InvalidRequest("The query picks no rows.")
    except InvalidRequest as e:
        problem = str(e)
    if problem or not rows:
        return Estimate(rows=total, calls=calls, cost=0, problem=problem)
    # The cost is worth knowing before a key is set, too.
    if settings.openrouter_key(datasets.org_of(dataset_id)) is None:
        problem = "Set your OpenRouter API key first."

    keys = {path: k for path, (_, k) in datasets.dataset_fields(dataset_id).items()}
    prices = {m.id: m for m in openrouter.models()}
    cost = 0.0
    for task in request.tasks:
        prompt_tokens = sum(
            prompts.count_tokens(prompts.render(task.template, row, keys)) for row in rows
        ) / len(rows)
        if task.type == "write":
            # Rewrites and translations are about as long as what they're given; summaries shorter.
            answer_tokens = prompt_tokens
        elif task.type == "extract":
            answer_tokens = _ANSWER_TOKENS["field"] * len(task.fields)
        else:
            answer_tokens = _ANSWER_TOKENS["classify"] * max(1, len(task.options))
        answer_tokens += _ANSWER_TOKENS["reason"] if task.reason else 0
        for model in task.models:
            instructions = (
                prompts.count_tokens(tasks.llm_instructions(task))
                if prices[model].kind == "llm"
                else 0
            )
            cost += total * (
                (prompt_tokens + instructions) * prices[model].prompt_price
                + answer_tokens * prices[model].completion_price
            )
    return Estimate(rows=total, calls=calls, cost=cost, problem=problem)


def get_run(run_id: str) -> Run:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"Run {run_id} not found")
    return _from_row(row)


def check_access(org_id: str, run_id: str) -> None:
    """Raise NotFound unless the run makes one of the organisation's datasets."""
    try:
        datasets.check_access(org_id, get_run(run_id).dataset_id)
    except NotFound:
        raise NotFound(f"Run {run_id} not found") from None


def stop_run(run_id: str) -> Run:
    """Stop after the calls in flight; a queued run stops right away. Resume continues it."""
    run = get_run(run_id)
    status = {"queued": "stopped", "running": "stopping"}.get(run.status)
    if status is None:
        raise InvalidRequest(f"The run is {run.status}, not running.")
    _set(run_id, status=status)
    return get_run(run_id)


def resume_run(run_id: str) -> Run:
    """Queue a stopped or failed run again, or a done one with failed answers. It first asks the
    answers that failed again, then continues from its first unwritten chunk."""
    run = get_run(run_id)
    failed = any(c.failed for c in run.costs)
    if run.status not in ("stopped", "failed") and not (run.status == "done" and failed):
        raise InvalidRequest(f"The run is {run.status}, with nothing to resume.")
    if run.status == "done":
        datasets.reopen_run_dataset(run.dataset_id)
    _set(run_id, status="queued", error=None)
    _wake.set()
    return get_run(run_id)


def start_runner() -> None:
    """Start a runner thread, for `rowlab serve`. On SQLite it is the only runner, so every run
    still marked running was cut off and is queued again straight away."""
    recover_interrupted_runs(STALE_SECONDS if config().postgres else 0)
    threading.Thread(target=run_forever, name="rowlab-runner", daemon=True).start()


def recover_interrupted_runs(stale_after: float | None = None) -> None:
    """Queue runs whose runner stopped (a server stop, a crash); they continue where they were. A
    runner saves its run's progress twice a second, so a run silent for `stale_after` seconds
    (`STALE_SECONDS` by default) has none."""
    seconds = STALE_SECONDS if stale_after is None else stale_after
    stale = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    with db.connect() as conn:
        conn.execute(
            "UPDATE runs SET status = 'queued' WHERE status = 'running' AND updated_at <= ?",
            (stale,),
        )
        conn.execute(
            "UPDATE runs SET status = 'stopped' WHERE status = 'stopping' AND updated_at <= ?",
            (stale,),
        )


def process_next() -> bool:
    """Claim the oldest queued run, if there is one, and process it. Returns whether there was.
    Several runners can share the queue: each claims a different run."""
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE runs SET status = 'running', updated_at = ? WHERE id = (SELECT id FROM runs"
            f" WHERE status = 'queued' ORDER BY created_at LIMIT 1{db.skip_locked()}) RETURNING id",
            (datetime.now(UTC).isoformat(),),
        ).fetchone()
    if row is None:
        return False
    _process(row["id"])
    return True


def run_forever() -> None:
    """Process queued runs, oldest first, one at a time; `rowlab runner` runs just this. While idle,
    runs whose runner stopped (another process that crashed) are queued again."""
    while True:
        try:
            if process_next():
                continue
            recover_interrupted_runs()
        except Exception:
            # The run is marked failed with its error; log it and keep serving the others.
            log.exception("Run failed")
        _wake.wait(timeout=5)
        _wake.clear()


def _process(run_id: str) -> None:
    run = get_run(run_id)
    _set(run_id, status="running")
    try:
        org_id = datasets.org_of(run.dataset_id)
        api_key = settings.openrouter_key(org_id)
        if api_key is None:
            raise InvalidRequest("Set your OpenRouter API key first.")
        keys = {path: k for path, (_, k) in datasets.dataset_fields(run.dataset_id).items()}
        # Answers that failed in the chunks already written are asked again first.
        for chunk in range(run.next_chunk):
            if not any(c.failed for c in run.costs):
                break
            if not _process_chunk(run, chunk, keys, org_id, api_key, retry=True):
                _set(run_id, status="stopped")
                return
            run = get_run(run_id)
        chunks = -(-run.row_count // CHUNK_ROWS)
        for chunk in range(run.next_chunk, chunks):
            if not _process_chunk(run, chunk, keys, org_id, api_key):
                _set(run_id, status="stopped")
                return
            run = get_run(run_id)
        datasets.finish_run_dataset(run.dataset_id)
        _set(run_id, status="done")
    except Exception as e:
        _set(run_id, status="failed", error=str(e))
        raise


def _process_chunk(
    run: Run,
    chunk: int,
    keys: dict[str, list[str]],
    org_id: str,
    api_key: str,
    *,
    retry: bool = False,
) -> bool:
    """Ask every task and model for the chunk's rows and write its part file. With `retry`, the part
    is already written: only its failed answers are asked again, past the response cache, and it is
    written again. Returns False, writing nothing, if the run was stopped meanwhile."""
    rows = datasets.read_run_rows(run.dataset_id, offset=chunk * CHUNK_ROWS, limit=CHUNK_ROWS)
    name = f"part-{chunk:06d}"
    written = datasets.read_run_part(run.dataset_id, name) if retry else {}
    # Calls in the chunks already written; a chunk being redone after a stop counts from zero.
    per_row = sum(len(task.models) for task in run.config.tasks)
    done_before = chunk * CHUNK_ROWS * per_row
    units = [
        (row, task, model)
        for row in rows
        for task in run.config.tasks
        for model in task.models
        if not retry or _failed(written[row[ROW_ID]], task, model)
    ]
    if not units:
        return True
    stopping = threading.Event()
    answers: list[_Answer | None] = [None] * len(units)

    def ask(i: int) -> None:
        if stopping.is_set():
            return
        row, task, model = units[i]
        prompt = prompts.render(task.template, row, keys)
        answers[i] = _ask(task, model, prompt, org_id, api_key, fresh=retry)

    with ThreadPoolExecutor(CONCURRENCY) as pool:
        futures = [pool.submit(ask, i) for i in range(len(units))]
        while not all(f.done() for f in futures):
            time.sleep(PROGRESS_INTERVAL_SECONDS)
            # Saving progress also shows other runners this run still has its runner.
            if retry:
                _set(run.id)
            else:
                _set(run.id, done=done_before + sum(a is not None for a in answers))
            # A deleted dataset takes its run with it.
            if _status(run.id) in ("stopping", None):
                stopping.set()
        for future in futures:
            future.result()
    if stopping.is_set():
        return False

    by_row: dict[int, dict[str, Any]] = {
        row[ROW_ID]: dict(written.get(row[ROW_ID], {})) for row in rows
    }
    for (row, task, model), answer in zip(units, answers):
        assert answer is not None
        out = by_row[row[ROW_ID]]
        failed = [f for f in out.get(datasets.FAILED) or [] if f != f"{task.id} {model}"]
        if answer.error is None:
            out |= tasks.with_model(task, model, answer.values)
        else:
            failed.append(f"{task.id} {model}")
        out[datasets.FAILED] = failed
    _write_part(run.dataset_id, run.config.tasks, name, by_row)
    costs = {(c.task_id, c.model): c for c in run.costs}
    for (_, task, model), answer in zip(units, answers):
        assert answer is not None
        cost = costs.setdefault(
            (task.id, model), TaskModelCost(task_id=task.id, model=model, cost=0, failed=0)
        )
        cost.cost += 0 if answer.cached else answer.cost
        if retry:
            cost.failed -= answer.error is None
        else:
            cost.failed += answer.error is not None
    progress = {} if retry else {"next_chunk": chunk + 1, "done": done_before + len(units)}
    _set(
        run.id,
        **progress,
        costs=json.dumps([c.model_dump() for c in costs.values()]),
        cost=sum(c.cost for c in costs.values()),
    )
    return True


def _failed(written: dict[str, Any], task: Task, model: str) -> bool:
    """Whether a model failed a task in a written row."""
    return f"{task.id} {model}" in (written.get(datasets.FAILED) or [])


def _write_part(
    dataset_id: str, run_tasks: list[Task], name: str, by_row: dict[int, dict[str, Any]]
) -> None:
    """Write answers as one Parquet file: `__row_id`, every answer column (empty where the model
    failed), and `__failed`, which models failed which tasks, as `<task id> <model>`. Written to a
    temporary name first, so a part is complete or absent."""
    columns = [
        (column, sql_type)
        for task in run_tasks
        for model in task.models
        for column, sql_type in tasks.columns(task, model)
    ]
    columns.append((datasets.FAILED, "VARCHAR[]"))
    with storage.connect() as con:
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
        storage.write(
            con, "SELECT * FROM part", storage.location(dataset_id, "parts", f"{name}.parquet")
        )


def _ask(
    task: Task, model: str, prompt: str, org_id: str, api_key: str, *, fresh: bool = False
) -> _Answer:
    """One task for one row from one model, as base columns. `fresh` asks past the cache."""
    decision = openrouter.model_kind(model) == "decision"
    try:
        if decision:
            questions = tasks.decision_questions(task)
            response = openrouter.decide(
                model, prompt, questions, org_id=org_id, api_key=api_key, fresh=fresh
            )
        else:
            messages = tasks.llm_messages(task, prompt)
            schema = tasks.llm_schema(task)
            response = openrouter.complete(
                model, messages, schema, org_id=org_id, api_key=api_key, fresh=fresh
            )
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
