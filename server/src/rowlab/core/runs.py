"""Runs: tasks asked by models about the rows a query picks, adding answer columns to the dataset,
by runners taking turns.

A run asks only for answers its dataset doesn't have yet. A cell an earlier run answered (a try on a
few rows, say) is skipped, and so is a row missing a value the prompt uses, e.g. an earlier answer
that failed. So starting the same run again, after a stop or a failure, asks only what is still missing.

The rows a run asks about are listed when it starts (`runs/{id}/asked.parquet`), and it works in chunks
of them: chunk k is always the same rows. A chunk's answers are written to `runs/{id}/part-{k}.parquet`
in one go, and only then does the run's bookmark (`next_chunk`) move on. So a stop, a crash or a
restart loses at most the chunk in progress, and redoing it costs nothing: the replies paid for are
journaled until the chunk is written (see `replies`). When the run ends (done, stopped or failed), its
parts are written out as one file, `runs/{id}.parquet`.

Runners take turns: a runner does one chunk of a run, then puts it back in the queue (`process_next`).
The next turn goes to a run that has waited long (`ROWLAB_RUN_WAIT_SECONDS`), or else to the one with
the least left to do, so a try on a few rows is done at once, even next to a big run.
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

from rowlab.core import (
    catalog,
    datasets,
    db,
    metrics,
    model_providers,
    prompts,
    replies,
    sql,
    storage,
    tasks,
    usage,
)
from rowlab.core.config import config
from rowlab.core.datasets import ROW_ID
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers.model_api import ProviderError, Request
from rowlab.core.storage import sql_ident, sql_string
from rowlab.core.tasks import Task

# Rows per chunk: the most work a stop or crash can lose (and redo for free).
CHUNK_ROWS = 500

# How often a run's progress is saved, and how often the runner checks for a stop.
PROGRESS_INTERVAL_SECONDS = 0.5

# A run whose progress hasn't been saved for this long has lost its runner, and is queued again.
STALE_SECONDS = 120

log = logging.getLogger(__name__)

Status = Literal["queued", "running", "stopping", "stopped", "done", "failed"]


class TaskModelCost(BaseModel):
    task_id: str
    model: str
    cost: float = Field(description="USD spent by this run; cached answers are free.")
    input_tokens: int = Field(0, description="Prompt tokens billed, as the provider counts them.")
    output_tokens: int = Field(0, description="Answer tokens billed.")
    failed: int = Field(description="Answers that failed; starting the run again asks them again.")


class RunRequest(BaseModel):
    """What to run: the tasks, on the rows a query picks."""

    sql: str = Field(
        sql.ALL_ROWS,
        description="Which rows to ask about: a SELECT over `data` returning `__row_id`; all rows "
        "by default. For a sample that grows without changing, order by a hash: `SELECT * FROM "
        "data ORDER BY md5('s1' || __row_id) LIMIT 50`.",
    )
    tasks: list[Task]


class Run(BaseModel):
    id: str
    dataset_id: str = Field(description="The dataset it adds answers to.")
    status: Status
    config: RunRequest = Field(description="The query and tasks it was started with.")
    models: dict[str, catalog.Model] = Field(
        {}, description="The models it asks, by id, with their kinds and prices as when it started."
    )
    columns: list[str] = Field(
        description="The answer columns it writes, without their `_proba` and `_reason` columns."
    )
    costs: list[TaskModelCost] = Field(description="Per task and model, so far.")
    row_count: int = Field(
        description="Rows it asks about: those the query picks that miss one of its answers."
    )
    done: int = Field(description="Answers asked so far, failed ones too.")
    total: int = Field(description="Answers it asks for.")
    cost: float = Field(description="USD spent so far; cached answers are free.")
    error: str | None = Field(description="Why the run failed.")
    created_by: str | None = Field(description="The user who started it; empty locally.")
    provider_id: str | None = Field(
        description="The model provider its calls go to, kept from when it started. Empty on the "
        "server's key."
    )
    created_at: datetime
    updated_at: datetime | None


class Estimate(BaseModel):
    rows: int = Field(description="Rows the query picks.")
    answered: int = Field(description="Answers those rows have already, which it won't ask again.")
    calls: int = Field(description="Answers it would ask models for.")
    missing_input: int = Field(
        description="Answers it would skip, because a column the prompt uses is empty in the row."
    )
    failed_before: int = Field(
        description="Of the answers it would ask for, those an earlier run asked and didn't get."
    )
    cost: float = Field(
        description="Roughly what it would cost in USD, from sample rows' token counts and the "
        "models' prices; replies kept from earlier runs would be free."
    )
    problem: str | None = Field(description="Why it can't run as it is, and what to change.")


class _Answer(BaseModel):
    values: dict[str, Any] = {}
    error: str | None = None
    cost: float = 0
    cached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


_wake = threading.Event()
# Set by `shut_down`: the runner takes no more turns.
_shutdown = threading.Event()


def create_run(dataset_id: str, request: RunRequest, created_by: str | None) -> Run:
    """Queue a run of every task with every model on the rows the query picks, asking only for the
    answers those rows don't have yet; started by `created_by` (a user; nobody locally)."""
    check(dataset_id, request)
    provider_id = model_providers.for_new_run(datasets.org_of(dataset_id))
    models = {model: catalog.get(model) for task in request.tasks for model in task.models}
    plan = _plan(dataset_id, request, rows=True)
    if not plan.rows:
        raise InvalidRequest("The query picks no rows.")
    if not plan.asked:
        raise InvalidRequest(
            "The rows the query picks have these answers already, or miss a column the prompt uses."
        )

    run_id = uuid.uuid4().hex
    asked = _asked_file(dataset_id, run_id)
    with storage.connect() as con:
        storage.write(
            con,
            f"SELECT unnest(?::BIGINT[]) AS {ROW_ID}, unnest(?::INTEGER[]) AS chunk",
            asked,
            [plan.asked, [i // CHUNK_ROWS for i in range(len(plan.asked))]],
        )
    try:
        with db.connect() as conn:
            # One at a time per dataset, so two runs never ask for the same answers.
            datasets.lock(conn, dataset_id)
            for other in _active(conn, dataset_id):
                same = _pairs(request) & _pairs(other.config)
                if same:
                    column, model = min(same)
                    raise InvalidRequest(
                        f"A run is already asking {tasks.model_slug(model)} for `{column}`: stop it, "
                        "or wait for it to end."
                    )
            for task in request.tasks:
                datasets.check_answers(dataset_id, task, list(task.models))
                for model in task.models:
                    datasets.add_answers(conn, dataset_id, task, model)
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO runs (id, dataset_id, status, config, models, columns, costs,"
                " row_count, total, created_at, queued_at, created_by, provider_id)"
                " VALUES (?, ?, 'queued', ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    dataset_id,
                    request.model_dump_json(),
                    json.dumps({k: m.model_dump() for k, m in models.items()}),
                    json.dumps([c for task in request.tasks for c in tasks.result_columns(task)]),
                    len(plan.asked),
                    plan.calls,
                    now,
                    now,
                    created_by,
                    provider_id,
                ),
            )
    except BaseException:
        storage.delete(asked)
        raise
    _wake.set()
    return get_run(run_id)


def list_runs(dataset_id: str) -> list[Run]:
    """The dataset's runs, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,)
        ).fetchall()
    return [_from_row(row) for row in rows]


def _active(conn: db.Connection, dataset_id: str) -> list[Run]:
    rows = conn.execute(
        f"SELECT * FROM runs WHERE dataset_id = ? AND status IN {datasets._ACTIVE}", (dataset_id,)
    ).fetchall()
    return [_from_row(row) for row in rows]


def _pairs(request: RunRequest) -> set[tuple[str, str]]:
    """The answers a run asks for, as (column, model)."""
    return {(task.column, model) for task in request.tasks for model in task.models}


def check(dataset_id: str, request: RunRequest) -> None:
    """Raise InvalidRequest, naming the task, if the run can't go as configured."""
    if not request.tasks:
        raise InvalidRequest("Add a task.")
    if len({t.id for t in request.tasks}) != len(request.tasks) or any(
        not t.id for t in request.tasks
    ):
        raise InvalidRequest("Each task needs a unique, nonempty id.")
    on_server_key = model_providers.status(datasets.org_of(dataset_id)) == "server"
    for task in request.tasks:
        try:
            tasks.check(task)
            for model in task.models:
                found = catalog.get(model)
                # The server pays: only for the models it lists, not any OpenRouter has.
                if on_server_key and not found.listed:
                    raise InvalidRequest(
                        f"{model} isn't on rowlab's list, and this server's own key pays for runs. "
                        "Pick a listed model."
                    )
                kind = found.kind
                if kind == "decision" and task.type in tasks.LLM_ONLY:
                    raise InvalidRequest(
                        f"{task.type.title()} needs an LLM: {tasks.model_slug(model)} is a "
                        "decision model."
                    )
                if kind == "decision" and task.reason:
                    raise InvalidRequest(
                        f"Only LLMs give a reason: {tasks.model_slug(model)} is a decision model."
                    )
            datasets.check_answers(dataset_id, task, list(task.models))
        except InvalidRequest as e:
            raise InvalidRequest(f"Task {task.column or 'without a column name'}: {e}") from e
    columns = [c for task in request.tasks for c in tasks.result_columns(task)]
    duplicates = sorted({c for c in columns if columns.count(c) > 1})
    if duplicates:
        raise InvalidRequest(f"Two tasks write the same column: {', '.join(duplicates)}.")


class _Plan(BaseModel):
    rows: int = 0
    asked: list[int] = []
    calls: int = 0
    answered: int = 0
    missing_input: int = 0
    failed_before: int = 0
    # Answers to ask for, by task id and model.
    by_model: dict[tuple[str, str], int] = {}


def _plan(dataset_id: str, request: RunRequest, *, rows: bool = False) -> _Plan:
    """What a run would ask for: per task and model, the rows the query picks that miss the
    answer and have the prompt's inputs; with `rows`, the rows to ask about."""
    keys = {path: k for path, (_, k) in datasets.dataset_fields(dataset_id).items()}
    have = {(a.name, a.model): a for a in datasets.answer_columns(dataset_id)}
    earlier = _ended(dataset_id)
    expressions = ["count(*)"]
    asks = []
    for task in request.tasks:
        present = (
            " AND ".join(
                f"t.{'.'.join(sql_ident(k) for k in path)} IS NOT NULL"
                for path in prompts.inputs(task.template, keys)
            )
            or "TRUE"
        )
        for model in task.models:
            columns = tasks.columns(task, model)
            if not columns:
                continue  # An extract task without fields: `check` says so.
            answer = columns[0][0]
            empty = f"t.{sql_ident(answer)} IS NULL" if (task.column, model) in have else "TRUE"
            ask = f"({empty} AND {present})"
            asks.append(ask)
            files = earlier.get((task.column, model), [])
            tried = (
                " OR ".join(
                    f"t.{ROW_ID} IN (SELECT {ROW_ID} FROM read_parquet({sql_string(f)})"
                    f" WHERE chunk < {n})"
                    for f, n in files
                )
                if files
                else "FALSE"
            )
            expressions += [
                f"count(*) FILTER ({ask})",
                f"count(*) FILTER (NOT ({empty}))",
                f"count(*) FILTER ({empty} AND NOT ({present}))",
                f"count(*) FILTER ({ask} AND ({tried}))",
            ]
    plan = _Plan()
    with sql.connect(dataset_id) as con:
        picked = f"SELECT * FROM data AS t WHERE {ROW_ID} IN ({sql.row_ids(con, request.sql)})"
        found = sql.execute(con, f"SELECT {', '.join(expressions)} FROM ({picked}) AS t").fetchone()
        if rows and asks:
            plan.asked = [
                r[0]
                for r in sql.execute(
                    con,
                    f"SELECT {ROW_ID} FROM ({picked}) AS t WHERE {' OR '.join(asks)}"
                    f" ORDER BY {ROW_ID}",
                ).fetchall()
            ]
    plan.rows = found[0]
    i = 1
    for task in request.tasks:
        for model in task.models:
            if not tasks.columns(task, model):
                continue
            ask, answered, missing, failed = found[i : i + 4]
            i += 4
            plan.by_model[(task.id, model)] = ask
            plan.calls += ask
            plan.answered += answered
            plan.missing_input += missing
            plan.failed_before += failed
    return plan


def _ended(dataset_id: str) -> dict[tuple[str, str], list[tuple[str, int]]]:
    """The rows ended runs asked about, as their files and how many chunks they got through, by
    the answers they asked for."""
    have = {(a.name, a.model) for a in datasets.answer_columns(dataset_id)}
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT id, config, next_chunk FROM runs WHERE dataset_id = ?"
            f" AND status NOT IN {datasets._ACTIVE} AND next_chunk > 0",
            (dataset_id,),
        ).fetchall()
    found: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for row in rows:
        for pair in _pairs(RunRequest.model_validate_json(row["config"])):
            if pair in have:
                found.setdefault(pair, []).append(
                    (_asked_file(dataset_id, row["id"]), row["next_chunk"])
                )
    return found


def _asked_file(dataset_id: str, run_id: str) -> str:
    return storage.location(dataset_id, "runs", run_id, "asked.parquet")


# Rows sampled to estimate prompt sizes, and roughly how many tokens answers take.
ESTIMATE_SAMPLE_ROWS = 20
_ANSWER_TOKENS = {"classify": 20, "field": 15, "reason": 60}
# Decision APIs wrap each call in their own instructions, billed as prompt tokens. Measured in
# November 2026, this makes typesafe/jev-1.14 (the default for yes/no) come out within a few percent;
# upstage/solar-decide adds a bit more, and many add next to none, so for those it errs high.
_DECISION_FRAMING_TOKENS = 260


def estimate(dataset_id: str, request: RunRequest) -> Estimate:
    """How many answers a run would ask for, and roughly what it would cost."""
    try:
        check(dataset_id, request)
        problem = None
    except InvalidRequest as e:
        problem = str(e)
    try:
        plan = _plan(dataset_id, request)
        rows = sql.query(
            dataset_id, sql.QueryRequest(sql=request.sql, limit=ESTIMATE_SAMPLE_ROWS)
        ).rows
    except InvalidRequest as e:
        return Estimate(
            rows=0,
            answered=0,
            calls=0,
            missing_input=0,
            failed_before=0,
            cost=0,
            problem=problem or str(e),
        )
    found = Estimate(
        rows=plan.rows,
        answered=plan.answered,
        calls=plan.calls,
        missing_input=plan.missing_input,
        failed_before=plan.failed_before,
        cost=0,
        problem=problem,
    )
    if not problem and plan.rows == 0:
        found.problem = "The query picks no rows."
    if found.problem or not rows:
        return found
    # The cost is worth knowing before a provider is added, too.
    if model_providers.status(datasets.org_of(dataset_id)) is None:
        found.problem = model_providers.NO_PROVIDER

    keys = {path: k for path, (_, k) in datasets.dataset_fields(dataset_id).items()}
    prices = {model: catalog.get(model) for task in request.tasks for model in task.models}
    for task in request.tasks:
        prompts_by_row = [prompts.render(task.template, row, keys) for row in rows]
        if task.type == "write":
            # Rewrites and translations are about as long as what they're given; summaries shorter.
            answer_tokens = sum(prompts.count_tokens(p) for p in prompts_by_row) / len(rows)
        elif task.type == "extract":
            answer_tokens = _ANSWER_TOKENS["field"] * len(task.fields)
        else:
            answer_tokens = _ANSWER_TOKENS["classify"] * max(1, len(task.options))
        answer_tokens += _ANSWER_TOKENS["reason"] if task.reason else 0
        for model in task.models:
            # All of what is sent is billed: instructions, options and schema too, not just the prompt.
            prompt_tokens = sum(
                prompts.count_tokens(
                    json.dumps(
                        model_providers.request(
                            "openrouter", "", task, model, p, kind=prices[model].kind
                        ).body,
                        ensure_ascii=False,
                    )
                )
                for p in prompts_by_row
            ) / len(rows)
            if prices[model].kind == "decision":
                prompt_tokens += _DECISION_FRAMING_TOKENS
            found.cost += plan.by_model[(task.id, model)] * (
                prompt_tokens * prices[model].prompt_price
                + answer_tokens * prices[model].completion_price
            )
    return found


def get_run(run_id: str) -> Run:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"Run {run_id} not found")
    return _from_row(row)


def check_access(org_id: str, run_id: str) -> None:
    """Raise NotFound unless the run is on one of the organisation's datasets."""
    try:
        datasets.check_access(org_id, get_run(run_id).dataset_id)
    except NotFound:
        raise NotFound(f"Run {run_id} not found") from None


def stop_run(run_id: str) -> Run:
    """Stop after the calls in flight; a queued run stops right away. Starting the same run again
    asks for what it didn't get to."""
    run = get_run(run_id)
    if run.status == "queued":
        with db.connect() as conn:
            stopped = conn.execute(
                "UPDATE runs SET status = 'stopping' WHERE id = ? AND status = 'queued'", (run_id,)
            ).rowcount
        if stopped:
            _end(run_id, "stopped")
    elif run.status == "running":
        _set(run_id, status="stopping")
    else:
        raise InvalidRequest(f"The run is {run.status}, not running.")
    return get_run(run_id)


def _end(run_id: str, status: str, error: str | None = None) -> None:
    """End a run: write its parts out as one file, with its replies, then mark it."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT dataset_id, next_chunk FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return  # Deleted with its dataset.
    dataset_id, chunks = row["dataset_id"], row["next_chunk"]
    if chunks:
        parts = datasets.run_files(dataset_id, run_id, "running", chunks)
        with storage.connect() as con:
            storage.write(
                con,
                f"SELECT * FROM read_parquet([{', '.join(map(sql_string, parts))}])"
                f" ORDER BY {ROW_ID}",
                storage.location(dataset_id, "runs", f"{run_id}.parquet"),
            )
    replies.finish(dataset_id, run_id, chunks)
    _set(run_id, status=status, error=error)
    for part in datasets.run_files(dataset_id, run_id, "running", chunks):
        storage.delete(part)
    replies.delete_parts(dataset_id, run_id, chunks)


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
        stopping = conn.execute(
            "SELECT id FROM runs WHERE status = 'stopping' AND updated_at <= ?", (stale,)
        ).fetchall()
    for row in stopping:
        _end(row["id"], "stopped")


def process_next() -> bool:
    """Claim the next run, if there is one, and do one chunk of it. Returns whether there was one.
    Several runners can share the queue: each claims a different run."""
    now = datetime.now(UTC)
    long_ago = (now - timedelta(seconds=config().run_wait_seconds)).isoformat()
    left = f"(r.row_count + {CHUNK_ROWS - 1}) / {CHUNK_ROWS} - r.next_chunk"
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE runs SET status = 'running', updated_at = ? WHERE id = ("
            " SELECT r.id FROM runs r WHERE r.status = 'queued'"
            " ORDER BY CASE WHEN r.queued_at <= ? THEN 0 ELSE 1 END,"
            f" CASE WHEN r.queued_at <= ? THEN 0 ELSE {left} END, r.queued_at"
            f" LIMIT 1{db.skip_locked('r')}) RETURNING id",
            (now.isoformat(), long_ago, long_ago),
        ).fetchone()
    if row is None:
        return False
    _process(row["id"])
    return True


def run_forever() -> None:
    """Process queued runs a chunk at a time, until `shut_down`; `rowlab runner` runs just this.
    While idle, runs whose runner stopped (another process that crashed) are queued again."""
    metrics.CALL_SLOTS.set(config().runner_calls)
    while not _shutdown.is_set():
        try:
            if process_next():
                continue
            recover_interrupted_runs()
        except Exception:
            # The run is marked failed with its error; log it and keep serving the others.
            log.exception("Run failed")
        _wake.wait(timeout=5)
        _wake.clear()
    log.info("Runner shut down")


def shut_down() -> None:
    """Stop the runner gracefully, e.g. on SIGTERM: it takes no more turns, and a chunk under way
    stops after the calls in flight, with what they paid for journaled. Its run goes back in the queue
    for the next runner straight away."""
    _shutdown.set()
    _wake.set()


def _process(run_id: str) -> None:
    """One turn of a claimed run: its next chunk. Then it waits in the queue again, or ends."""
    run = get_run(run_id)
    chunks = -(-run.row_count // CHUNK_ROWS)
    try:
        org_id = datasets.org_of(run.dataset_id)
        use = model_providers.for_run(org_id, run.provider_id)
        keys = {path: k for path, (_, k) in datasets.dataset_fields(run.dataset_id).items()}
        chunk = _next_chunk(run_id)
        if chunk < chunks and not _process_chunk(run, chunk, keys, org_id, use):
            # Stopped by its user, or deleted; or this runner is shutting down and gives it back.
            _requeue(run_id)
            return
        if _next_chunk(run_id) >= chunks:
            _end(run_id, "done")
            metrics.RUNS_FINISHED.labels("done").inc()
            return
        _requeue(run_id)
    except Exception as e:
        _end(run_id, "failed", str(e))
        metrics.RUNS_FINISHED.labels("failed").inc()
        raise


def _requeue(run_id: str) -> None:
    """Put a running run back in the queue, or end it if it was stopped meanwhile."""
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        queued = conn.execute(
            "UPDATE runs SET status = 'queued', queued_at = ?, updated_at = ?"
            " WHERE id = ? AND status = 'running'",
            (now, now, run_id),
        ).rowcount
    if not queued and _status(run_id) == "stopping":
        _end(run_id, "stopped")


def _next_chunk(run_id: str) -> int:
    with db.connect() as conn:
        row = conn.execute("SELECT next_chunk FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"Run {run_id} not found")
    return row["next_chunk"]


def _chunk_rows(run: Run, chunk: int) -> list[dict[str, Any]]:
    """A chunk's rows, as `data` has them now: values and answers so far."""
    asked = sql_string(_asked_file(run.dataset_id, run.id))
    with storage.connect() as con:
        datasets.attach(con, run.dataset_id)
        rows = con.execute(
            f"SELECT to_json(t) FROM data AS t WHERE {ROW_ID} IN"
            f" (SELECT {ROW_ID} FROM read_parquet({asked}) WHERE chunk = ?) ORDER BY {ROW_ID}",
            [chunk],
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def _process_chunk(
    run: Run,
    chunk: int,
    keys: dict[str, list[str]],
    org_id: str,
    use: model_providers.Use,
) -> bool:
    """Ask every task and model for the chunk's rows that miss the answer and have the prompt's
    inputs, and write its part file, with the replies beside it. A reply already paid for, in the
    journal or kept by the dataset's runs, is used instead of asking. Returns False, writing nothing,
    if the run was stopped meanwhile, or the runner is shutting down: calls not yet started are not
    made."""
    rows = _chunk_rows(run, chunk)
    units = [
        (row, task, model)
        for row in rows
        for task in run.config.tasks
        if prompts.has_inputs(task.template, row, keys)
        for model in task.models
        if row.get(tasks.columns(task, model)[0][0]) is None
    ]
    models = _models(run)
    requests = [
        model_providers.request(
            use.type,
            use.model_prefix,
            task,
            model,
            prompts.render(task.template, row, keys),
            kind=models[model].kind,
        )
        for row, task, model in units
    ]
    request_keys = [replies.key(org_id, request) for request in requests]
    row_ids = [row[ROW_ID] for row in rows]
    found = replies.stored(
        run.dataset_id, [model for task in run.config.tasks for model in task.models], row_ids
    ) | replies.journaled(run.id)
    done_before = get_run(run.id).done
    stopping = threading.Event()
    given: list[_Answer | None] = [None] * len(units)
    # The replies to keep, written beside the part; those paid for now are journaled until it is.
    kept: list[replies.Reply | None] = [None] * len(units)
    paid: list[replies.Reply] = []
    # What the answers so far cost, by task and model, until it is added to the usage.
    spent: dict[tuple[str, str], usage.Spent] = {}
    spent_lock = threading.Lock()

    def ask(i: int) -> None:
        if stopping.is_set() or _shutdown.is_set():
            return
        row, task, model = units[i]
        saved = found.get(request_keys[i])
        try:
            answer, data = _ask(task, models[model], requests[i], use, saved)
        except KeyProblem:
            stopping.set()
            raise
        given[i] = answer
        # Only replies that could be read: one that couldn't is asked again next time.
        if data is not None and answer.error is None:
            kept[i] = (request_keys[i], row[ROW_ID], data)
        with spent_lock:
            _count(spent.setdefault((task.id, model), usage.Spent()), answer)
            if kept[i] is not None and saved is None:
                paid.append(kept[i])

    def record_spent() -> None:
        """Add what was spent since the last time to the usage, and journal the replies paid for:
        paid is paid, however the chunk ends."""
        with spent_lock:
            taken = dict(spent)
            spent.clear()
            journaled = list(paid)
        replies.journal(run.id, journaled)
        # Only once they are journaled: if that fails, the next try (or the `finally`) has them.
        with spent_lock:
            del paid[: len(journaled)]
        if taken:
            with db.connect() as conn:
                usage.add(
                    conn,
                    org_id=org_id,
                    user_id=run.created_by,
                    run_id=run.id,
                    paid_by=use.paid_by,
                    spent=taken,
                )
            metrics.count_spent(taken)

    try:
        with ThreadPoolExecutor(config().runner_calls) as pool:
            futures = [pool.submit(ask, i) for i in range(len(units))]
            while not all(f.done() for f in futures):
                time.sleep(PROGRESS_INTERVAL_SECONDS)
                # Saving progress also shows other runners this run still has its runner.
                _set(run.id, done=done_before + sum(a is not None for a in given))
                record_spent()
                # A deleted dataset takes its run with it.
                if _status(run.id) in ("stopping", None):
                    stopping.set()
            for future in futures:
                future.result()
    finally:
        record_spent()
    if any(answer is None for answer in given):
        return False

    by_row: dict[int, dict[str, Any]] = {row[ROW_ID]: {} for row in rows}
    answered: dict[tuple[str, str], int] = {}
    for (row, task, model), answer in zip(units, given):
        assert answer is not None
        if answer.error is None:
            by_row[row[ROW_ID]] |= tasks.with_model(task, model, answer.values)
            answered[(task.column, model)] = answered.get((task.column, model), 0) + 1
    replies.write_part(run.dataset_id, run.id, chunk, [r for r in kept if r is not None])
    write_part(run.dataset_id, run.id, chunk, tasks.part_columns(run.config.tasks), by_row)
    costs = {(c.task_id, c.model): c for c in get_run(run.id).costs}
    for (_, task, model), answer in zip(units, given):
        assert answer is not None
        cost = costs.setdefault(
            (task.id, model), TaskModelCost(task_id=task.id, model=model, cost=0, failed=0)
        )
        if not answer.cached:
            cost.cost += answer.cost
            cost.input_tokens += answer.input_tokens
            cost.output_tokens += answer.output_tokens
        cost.failed += answer.error is not None
    with db.connect() as conn:
        for (column, model), n in answered.items():
            conn.execute(
                "UPDATE answer_columns SET answered = answered + ?"
                " WHERE dataset_id = ? AND name = ? AND model = ?",
                (n, run.dataset_id, column, model),
            )
        conn.execute(
            "UPDATE runs SET next_chunk = ?, done = ?, costs = ?, cost = ?, updated_at = ?"
            " WHERE id = ?",
            (
                chunk + 1,
                done_before + len(units),
                json.dumps([c.model_dump() for c in costs.values()]),
                sum(c.cost for c in costs.values()),
                datetime.now(UTC).isoformat(),
                run.id,
            ),
        )
    if row_ids:
        replies.clear_journal(run.id, row_ids)
    return True


def write_part(
    dataset_id: str,
    run_id: str,
    chunk: int,
    columns: list[tuple[str, str]],
    by_row: dict[int, dict[str, Any]],
) -> None:
    """Write a chunk's answers as one Parquet file: `__row_id` and the run's answer `columns` (name
    and SQL type; empty where the model failed, or wasn't asked)."""
    with storage.connect() as con:
        con.execute(
            "CREATE TABLE part ("
            + ", ".join(
                [f"{sql_ident(ROW_ID)} BIGINT"] + [f"{sql_ident(n)} {t}" for n, t in columns]
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
        storage.write(con, "SELECT * FROM part", datasets.run_part(dataset_id, run_id, chunk))


def _count(spent: usage.Spent, answer: _Answer) -> None:
    """Add an answer to what was spent. Cached replies cost nothing and used no tokens this time."""
    spent.answers += answer.error is None
    spent.failed += answer.error is not None
    spent.cached += answer.cached and answer.error is None
    if not answer.cached:
        spent.cost += answer.cost
        spent.input_tokens += answer.input_tokens
        spent.output_tokens += answer.output_tokens


class KeyProblem(Exception):
    """The provider refuses the key, or it is out of credits: every call would fail alike, so the run
    fails with this. Starting it again once the key is fixed asks for what it didn't get."""


_KEY_PROBLEMS = {
    401: "The model provider refused the key. Change it in Settings → Providers, then start the "
    "run again",
    402: "The model provider's key is out of credits. Add some, then start the run again",
}


def _models(run: Run) -> dict[str, catalog.Model]:
    """The run's models as when it started; looked up for runs from before they were kept."""
    return {
        model: run.models.get(model) or catalog.get(model)
        for task in run.config.tasks
        for model in task.models
    }


def _ask(
    task: Task, model: catalog.Model, request: Request, use: model_providers.Use, saved: Any = None
) -> tuple[_Answer, Any]:
    """One task for one row from one model, as base columns, with the reply's data (None if there
    was no reply). `saved` is a reply already paid for, used instead of asking unless it can't be
    read as an answer (one kept before only readable replies were)."""
    if saved is not None:
        answer = _Answer(cached=True)
        try:
            answer.values = _read(task, model, saved)
            return answer, saved
        except tasks.AnswerFormatError:
            pass
    try:
        with metrics.CALLS_IN_FLIGHT.track_inprogress():
            response = model_providers.ask(use, request, model)
    except ProviderError as e:
        if e.status in _KEY_PROBLEMS:
            raise KeyProblem(f"{_KEY_PROBLEMS[e.status]} ({e})") from e
        return _Answer(error=str(e)), None
    # Paid for even when the reply turns out unusable.
    answer = _Answer(
        cost=response.cost,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    if response.data is None:
        answer.error = "The model's reply couldn't be read."
        return answer, None
    try:
        answer.values = _read(task, model, response.data)
    except tasks.AnswerFormatError as e:
        answer.error = str(e)
    return answer, response.data


def _read(task: Task, model: catalog.Model, data: Any) -> dict[str, Any]:
    if model.kind == "decision":
        return tasks.read_decision(task, data)
    return tasks.read_llm(task, data)


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
        models=json.loads(row["models"]),
        columns=json.loads(row["columns"]),
        costs=json.loads(row["costs"]),
        row_count=row["row_count"],
        done=row["done"],
        total=row["total"],
        cost=row["cost"],
        error=row["error"],
        created_by=row["created_by"],
        provider_id=row["provider_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
