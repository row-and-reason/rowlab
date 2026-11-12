"""Runs: tasks asked about the rows a query picks, making a new dataset, by runners taking turns.

Starting a run copies the selected rows into a new dataset, which shows up straight away;
they get their answers as the run goes. The run keeps
a frozen copy of its query and tasks. It works in chunks of those rows by `__row_id` (chunk k is always
the same rows). A chunk's answers are written to the dataset's `parts/part-{k}.parquet` in one go, and
only then does the run's bookmark (`next_chunk`) move on. So a stop, a crash or a restart loses at most
the chunk in progress, and redoing it costs nothing: the replies paid for are journaled until the chunk
is written (see `answers`). When every chunk is written, the dataset is written out as one Parquet
file.

Runners take turns: a runner does one chunk of a run, then puts it back in the queue (`process_next`).
The next turn goes to a run that has waited long (`ROWLAB_RUN_WAIT_SECONDS`), or else to the one with
the least left to do, so a try on a few rows is done at once, even next to a big run. An organisation
has at most `ROWLAB_RUNS_PER_ORG` runs going at once.
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

from rowlab.core import answers, datasets, db, prompts, settings, sql, storage, tasks, usage
from rowlab.core.config import config
from rowlab.core.datasets import ROW_ID
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.providers import openrouter
from rowlab.core.storage import sql_ident, sql_string
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

Status = Literal["queued", "running", "stopping", "stopped", "done", "failed", "manual"]

# Statuses of a run that still has work to do.
ACTIVE = ("queued", "running", "stopping")


class TaskModelCost(BaseModel):
    task_id: str
    model: str
    cost: float = Field(description="USD spent by this run; cached answers are free.")
    input_tokens: int = Field(0, description="Prompt tokens billed, as the provider counts them.")
    output_tokens: int = Field(0, description="Answer tokens billed.")
    failed: int = Field(description="Rows without an answer.")


class RunRequest(BaseModel):
    """What to run: the tasks, on the rows a query picks."""

    sql: str = Field(
        sql.ALL_ROWS,
        description="Which rows to ask about: a SELECT over `data` returning `__row_id`; all rows "
        "by default.",
    )
    tasks: list[Task]
    method: Literal["llm", "manual"] = Field(
        "llm", description="Label with models or enter labels manually."
    )


class Run(BaseModel):
    id: str
    dataset_id: str = Field(description="The dataset it makes.")
    status: Status
    config: RunRequest = Field(description="The query and tasks it was started with.")
    columns: list[str] = Field(
        description="The output columns; manual runs use the task's column name without a model suffix."
    )
    costs: list[TaskModelCost] = Field(description="Per task and model, so far.")
    row_count: int = Field(description="Rows it asks about: the rows in its scope.")
    next_chunk: int = Field(description="The first chunk of rows not yet written.")
    done: int = Field(description="Answers saved (or failed) so far.")
    total: int = Field(description="Answers the run asks for.")
    cost: float = Field(description="USD spent so far; cached answers are free.")
    error: str | None = Field(description="Why the run failed.")
    created_by: str | None = Field(description="The user who started it; empty locally.")
    created_at: datetime
    updated_at: datetime | None


class Estimate(BaseModel):
    rows: int = Field(description="Rows the run would ask about.")
    calls: int = Field(description="Model calls it would make.")
    cost: float = Field(
        description="Roughly what it would cost in USD, from sample rows' token counts and the models' "
        "prices; answers already given to the same rows in the dataset's tree would be free."
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
    """Queue a run of every task with every model on the rows the query picks, started by
    `created_by` (a user; nobody locally). Its dataset, with the selected rows of the dataset and empty
    answer columns, is created right away."""
    request = _normalized(request)
    manual = request.method == "manual"
    check(dataset_id, request)
    if request.method == "llm" and settings.openrouter_key(datasets.org_of(dataset_id)) is None:
        raise InvalidRequest("Set your OpenRouter API key first.")
    with sql.connect(dataset_id) as con:
        query = sql.row_ids(con, request.sql)
        asked = [r[0] for r in sql.execute(con, f"{query} ORDER BY {ROW_ID}").fetchall()]
    if not asked:
        raise InvalidRequest("The query picks no rows.")

    made_id = datasets.write_run_rows(dataset_id, asked)
    try:
        # An empty part gives the answer columns their types before any chunk is written.
        datasets.write_run_part(
            made_id, tasks.part_columns(request.tasks, manual=manual), "part-schema", {}
        )
        datasets.register_run_dataset(made_id, dataset_id)
        run_id = uuid.uuid4().hex
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, dataset_id, status, config, columns, costs,"
                " row_count, total, created_at, queued_at, created_by)"
                " VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?)",
                (
                    run_id,
                    made_id,
                    "manual" if manual else "queued",
                    request.model_dump_json(),
                    json.dumps(tasks.answer_columns(request.tasks, manual=manual)),
                    len(asked),
                    len(asked) * sum(1 if manual else len(task.models) for task in request.tasks),
                    datetime.now(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),
                    created_by,
                ),
            )
    except BaseException:
        with db.connect() as conn:
            conn.execute("DELETE FROM datasets WHERE id = ?", (made_id,))
        storage.delete_dataset(made_id)
        raise
    _wake.set()
    return get_run(run_id)


def _normalized(request: RunRequest) -> RunRequest:
    """The request as it runs: manual tasks ask no models and give no reasons."""
    if request.method == "llm":
        return request
    return request.model_copy(
        update={
            "tasks": [t.model_copy(update={"models": [], "reason": False}) for t in request.tasks]
        }
    )


def check(dataset_id: str, request: RunRequest) -> None:
    """Raise InvalidRequest, naming the task, if the run can't go as configured. Takes a
    `_normalized` request."""
    if not request.tasks:
        raise InvalidRequest("Add a task.")
    if len({t.id for t in request.tasks}) != len(request.tasks) or any(
        not t.id for t in request.tasks
    ):
        raise InvalidRequest("Each task needs a unique, nonempty id.")
    parent = datasets.get_dataset(dataset_id)
    if parent.run and parent.run.status == "manual":
        raise InvalidRequest("Finish this dataset before starting another run on it.")
    manual = request.method == "manual"
    for task in request.tasks:
        try:
            tasks.check(task, manual=manual)
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
    columns = tasks.answer_columns(request.tasks, manual=manual)
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
# Decision APIs wrap each call in their own instructions, billed as prompt tokens. Measured in
# November 2026, this makes typesafe/jev-1.14 (the default for yes/no) come out within a few percent;
# upstage/solar-decide adds a bit more, and many add next to none, so for those it errs high.
_DECISION_FRAMING_TOKENS = 260


def estimate(dataset_id: str, request: RunRequest) -> Estimate:
    """How many rows and model calls a run would take, and roughly what it would cost."""
    request = _normalized(request)
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
    if request.method == "manual":
        return Estimate(rows=total, calls=0, cost=0, problem=problem)
    if problem or not rows:
        return Estimate(rows=total, calls=calls, cost=0, problem=problem)
    # The cost is worth knowing before a key is set, too.
    if settings.openrouter_key(datasets.org_of(dataset_id)) is None:
        problem = "Set your OpenRouter API key first."

    keys = {path: k for path, (_, k) in datasets.dataset_fields(dataset_id).items()}
    prices = {m.id: m for m in openrouter.models()}
    cost = 0.0
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
                prompts.count_tokens(json.dumps(_request(task, model, p).body, ensure_ascii=False))
                for p in prompts_by_row
            ) / len(rows)
            if prices[model].kind == "decision":
                prompt_tokens += _DECISION_FRAMING_TOKENS
            cost += total * (
                prompt_tokens * prices[model].prompt_price
                + answer_tokens * prices[model].completion_price
            )
    return Estimate(rows=total, calls=calls, cost=cost, problem=problem)


def get_run(run_id: str) -> Run:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"Run {run_id} not found")
    run = _from_row(row)
    if run.status == "manual":
        # Parts are authoritative if a save stopped before updating progress.
        run.done = manual_done(run)
    return run


def manual_done(run: Run) -> int:
    """Saved answers, including false and empty text; entirely empty answers are unanswered."""
    expressions = [
        "count(*) FILTER (WHERE "
        + " OR ".join(f"{sql_ident(name)} IS NOT NULL" for name, _ in tasks.manual_columns(task))
        + ")"
        for task in run.config.tasks
    ]
    with storage.connect() as con:
        return con.execute(
            f"SELECT {' + '.join(expressions)} FROM read_parquet({sql_string(storage.location(run.dataset_id, 'parts', '*.parquet'))})"
        ).fetchone()[0]


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
    _set(
        run_id,
        status="queued",
        error=None,
        queued_at=datetime.now(UTC).isoformat(),
        # Its failed answers are asked again first, chunk by chunk.
        retry_chunk=0 if failed and run.next_chunk else None,
    )
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
    """Claim the next run, if there is one, and do one chunk of it. Returns whether there was one.
    Several runners can share the queue: each claims a different run."""
    now = datetime.now(UTC)
    long_ago = (now - timedelta(seconds=config().run_wait_seconds)).isoformat()
    # Chunks left, counting failed answers still to ask again.
    left = (
        f"(r.row_count + {CHUNK_ROWS - 1}) / {CHUNK_ROWS} - r.next_chunk"
        " + coalesce(r.next_chunk - r.retry_chunk, 0)"
    )
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE runs SET status = 'running', updated_at = ? WHERE id = ("
            " SELECT r.id FROM runs r JOIN datasets d ON d.id = r.dataset_id"
            " WHERE r.status = 'queued' AND ("
            "  SELECT count(*) FROM runs o JOIN datasets od ON od.id = o.dataset_id"
            "  WHERE od.org_id = d.org_id AND o.status IN ('running', 'stopping')) < ?"
            " ORDER BY CASE WHEN r.queued_at <= ? THEN 0 ELSE 1 END,"
            f" CASE WHEN r.queued_at <= ? THEN 0 ELSE {left} END, r.queued_at"
            f" LIMIT 1{db.skip_locked('r')}) RETURNING id",
            (now.isoformat(), config().runs_per_org, long_ago, long_ago),
        ).fetchone()
    if row is None:
        return False
    _process(row["id"])
    return True


def run_forever() -> None:
    """Process queued runs a chunk at a time, until `shut_down`; `rowlab runner` runs just this.
    While idle, runs whose runner stopped (another process that crashed) are queued again."""
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
    """One turn of a claimed run: one chunk of failed answers to ask again, or else the next chunk.
    Then it waits in the queue again, or is done."""
    run = get_run(run_id)
    retry = _retry_chunk(run_id)
    if retry is not None and (retry >= run.next_chunk or not any(c.failed for c in run.costs)):
        retry = None
    chunks = -(-run.row_count // CHUNK_ROWS)
    try:
        org_id = datasets.org_of(run.dataset_id)
        api_key = settings.openrouter_key(org_id)
        if api_key is None:
            raise InvalidRequest("Set your OpenRouter API key first.")
        keys = {path: k for path, (_, k) in datasets.dataset_fields(run.dataset_id).items()}
        if retry is not None:
            finished = _process_chunk(run, retry, keys, org_id, api_key, retry=True)
            retry += 1
        else:
            finished = run.next_chunk >= chunks or _process_chunk(
                run, run.next_chunk, keys, org_id, api_key
            )
        if not finished:
            # Stopped by its user, or deleted; or this runner is shutting down and gives it back.
            with db.connect() as conn:
                conn.execute(
                    "UPDATE runs SET status = CASE WHEN status = 'stopping' THEN 'stopped'"
                    " ELSE 'queued' END, updated_at = ? WHERE id = ?",
                    (datetime.now(UTC).isoformat(), run_id),
                )
            return
        run = get_run(run_id)
        retry = retry if retry is not None and retry < run.next_chunk else None
        if retry is None and run.next_chunk >= chunks:
            datasets.finish_run_dataset(run.dataset_id)
            answers.finish(run.dataset_id)
            _set(run_id, status="done", retry_chunk=None)
            return
        # Back in the queue, unless it was stopped meanwhile.
        now = datetime.now(UTC).isoformat()
        with db.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = CASE WHEN status = 'stopping' THEN 'stopped'"
                " ELSE 'queued' END, retry_chunk = ?, queued_at = ?, updated_at = ? WHERE id = ?",
                (retry, now, now, run_id),
            )
    except Exception as e:
        _set(run_id, status="failed", error=str(e))
        raise


def _retry_chunk(run_id: str) -> int | None:
    with db.connect() as conn:
        row = conn.execute("SELECT retry_chunk FROM runs WHERE id = ?", (run_id,)).fetchone()
    return row["retry_chunk"]


def _process_chunk(
    run: Run,
    chunk: int,
    keys: dict[str, list[str]],
    org_id: str,
    api_key: str,
    *,
    retry: bool = False,
) -> bool:
    """Ask every task and model for the chunk's rows and write its part file, with the replies beside
    it. A reply already paid for, in the journal or the tree's done datasets, is used instead of
    asking.
    With `retry`, the part is already written: only its failed answers are asked again, past the
    replies kept, and it is written again. Returns False, writing nothing, if the run was stopped
    meanwhile, or the runner is shutting down: calls not yet started are not made."""
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
    requests = [
        _request(task, model, prompts.render(task.template, row, keys))
        for row, task, model in units
    ]
    request_keys = [answers.key(org_id, request) for request in requests]
    row_ids = [row[ROW_ID] for row in rows]
    # A retry asks past the replies kept, but not past those paid for in it before a stop or crash.
    found = (
        {}
        if retry
        else answers.stored(
            run.dataset_id, [model for task in run.config.tasks for model in task.models], row_ids
        )
    ) | answers.journaled(run.id)
    stopping = threading.Event()
    given: list[_Answer | None] = [None] * len(units)
    # The replies, to write beside the part; those paid for now are journaled until it is.
    replies: list[answers.Reply | None] = [None] * len(units)
    paid: list[answers.Reply] = []
    # What the answers so far cost, by task and model, until it is added to the usage.
    spent: dict[tuple[str, str], usage.Spent] = {}
    spent_lock = threading.Lock()

    def ask(i: int) -> None:
        if stopping.is_set() or _shutdown.is_set():
            return
        row, task, model = units[i]
        saved = found.get(request_keys[i])
        try:
            answer, data = _ask(task, model, requests[i], api_key, saved)
        except KeyProblem:
            stopping.set()
            raise
        given[i] = answer
        if data is not None:
            replies[i] = (request_keys[i], row[ROW_ID], data)
        with spent_lock:
            _count(spent.setdefault((task.id, model), usage.Spent()), answer)
            if data is not None and saved is None:
                paid.append(replies[i])

    def record_spent() -> None:
        """Add what was spent since the last time to the usage, and journal the replies paid for:
        paid is paid, however the chunk ends."""
        with spent_lock:
            taken = dict(spent)
            spent.clear()
            journaled = list(paid)
        answers.journal(run.id, journaled)
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
                    paid_by=settings.paid_by(),
                    spent=taken,
                )

    try:
        with ThreadPoolExecutor(CONCURRENCY) as pool:
            futures = [pool.submit(ask, i) for i in range(len(units))]
            while not all(f.done() for f in futures):
                time.sleep(PROGRESS_INTERVAL_SECONDS)
                # Saving progress also shows other runners this run still has its runner.
                if retry:
                    _set(run.id)
                else:
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

    by_row: dict[int, dict[str, Any]] = {
        row[ROW_ID]: dict(written.get(row[ROW_ID], {})) for row in rows
    }
    for (row, task, model), answer in zip(units, given):
        assert answer is not None
        out = by_row[row[ROW_ID]]
        failed = [f for f in out.get(datasets.FAILED) or [] if f != f"{task.id} {model}"]
        if answer.error is None:
            out |= tasks.with_model(task, model, answer.values)
        else:
            failed.append(f"{task.id} {model}")
        out[datasets.FAILED] = failed
    answers.write_part(run.dataset_id, name, [r for r in replies if r is not None])
    datasets.write_run_part(
        run.dataset_id, tasks.part_columns(run.config.tasks, manual=False), name, by_row
    )
    costs = {(c.task_id, c.model): c for c in run.costs}
    for (_, task, model), answer in zip(units, given):
        assert answer is not None
        cost = costs.setdefault(
            (task.id, model), TaskModelCost(task_id=task.id, model=model, cost=0, failed=0)
        )
        if not answer.cached:
            cost.cost += answer.cost
            cost.input_tokens += answer.input_tokens
            cost.output_tokens += answer.output_tokens
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
    answers.clear_journal(run.id, row_ids)
    return True


def _count(spent: usage.Spent, answer: _Answer) -> None:
    """Add an answer to what was spent. Cached replies cost nothing and used no tokens this time."""
    spent.answers += answer.error is None
    spent.failed += answer.error is not None
    spent.cached += answer.cached and answer.error is None
    if not answer.cached:
        spent.cost += answer.cost
        spent.input_tokens += answer.input_tokens
        spent.output_tokens += answer.output_tokens


def _failed(written: dict[str, Any], task: Task, model: str) -> bool:
    """Whether a model failed a task in a written row."""
    return f"{task.id} {model}" in (written.get(datasets.FAILED) or [])


class KeyProblem(Exception):
    """OpenRouter refuses the key, or it is out of credits: every call would fail alike, so the run
    fails with this, to be resumed once the key is fixed."""


_KEY_PROBLEMS = {
    401: "OpenRouter refused the key. Change it in Settings → Providers, then resume the run",
    402: "The OpenRouter key is out of credits. Add some at openrouter.ai, then resume the run",
}


def _request(task: Task, model: str, prompt: str) -> openrouter.Request:
    """The call asking one task for one row of one model."""
    if openrouter.model_kind(model) == "decision":
        return openrouter.decision_request(model, prompt, tasks.decision_questions(task))
    return openrouter.completion_request(
        model, tasks.llm_messages(task, prompt), tasks.llm_schema(task)
    )


def _ask(
    task: Task, model: str, request: openrouter.Request, api_key: str, saved: Any = None
) -> tuple[_Answer, Any]:
    """One task for one row from one model, as base columns, with the reply's data (None if there
    was no reply). `saved` is a reply already paid for, used instead of asking."""
    if saved is not None:
        answer, data = _Answer(cached=True), saved
    else:
        try:
            response = openrouter.post(request, api_key)
        except openrouter.OpenRouterError as e:
            if e.status in _KEY_PROBLEMS:
                raise KeyProblem(f"{_KEY_PROBLEMS[e.status]} ({e})") from e
            return _Answer(error=str(e)), None
        # Paid for even when the reply turns out unusable.
        answer = _Answer(
            cost=response.cost,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        data = response.data
    try:
        if request.path == openrouter.DECISIONS:
            answer.values = tasks.read_decision(task, data)
        else:
            answer.values = tasks.read_llm(task, data)
    except tasks.AnswerFormatError as e:
        answer.error = str(e)
    return answer, data


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
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
