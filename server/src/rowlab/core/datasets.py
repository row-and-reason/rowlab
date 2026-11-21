"""Datasets: files ingested once into Parquet with a stable `__row_id`, then explored with DuckDB.

A dataset is the rows of one file, and the answer columns runs and people add to it. Its file
(`data.parquet`) is never changed. Each run writes its answers to files of its own (`runs/`, see
`runs`); labels people set are kept in the database (see `labels`). Queries see all of it as one table,
`data`: the file's rows joined with every run's answers and the labels, by `__row_id` (`attach`).

`answer_columns` records each task and model a dataset has answers from, and each labelled task, with
the question it answers. A name keeps its meaning: asking a different question under a name in use is
refused, and asking the same one again adds to the same columns.
"""

import gzip
import json
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import duckdb
import duckdb.sqltypes
from pydantic import BaseModel, Field

from rowlab.core import connections, db, network, storage, tasks
from rowlab.core.config import config
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.storage import sql_ident, sql_string
from rowlab.core.tasks import Task

ROW_ID = "__row_id"

Format = Literal["csv", "json", "jsonl", "parquet"]

# File extensions dropped from names: every dataset is stored as Parquet, whatever it came from.
EXTENSIONS = (".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".parquet")

# DuckDB table functions per format; `?` is the file path and `{compression}` is `gzip` or `none`.
# CSV delimiters are sniffed by DuckDB. JSON reads an array of objects or one object per line; nested
# values stay as structs and lists.
READERS = {
    "csv": "read_csv(?, compression = '{compression}')",
    "json": "read_json(?, format = 'auto', compression = '{compression}')",
    "jsonl": "read_json(?, format = 'auto', compression = '{compression}')",
    "parquet": "read_parquet(?)",
}


class Column(BaseModel):
    name: str
    type: str


class AnswerColumn(BaseModel):
    """Answers to one task from one model, or labels people set for one task."""

    name: str = Field(description="The task's column, e.g. `fallacy`.")
    model: str | None = Field(description="The model that answers; empty for labels people set.")
    task: Task = Field(description="The question its answers are to.")
    columns: list[str] = Field(
        description="Its columns in `data`, e.g. `fallacy__jev-1.14` and `fallacy__jev-1.14_proba`."
    )
    answered: int = Field(description="Rows with an answer.")
    cost: float = Field(description="USD runs spent on it; cached answers are free.")


class DatasetSummary(BaseModel):
    id: str
    name: str
    source: str
    row_count: int
    size_bytes: int = Field(description="Of its file; answers are kept beside it.")
    created_at: datetime
    answer_columns: int = Field(description="Tasks with answers from a model, or labels.")
    active_runs: int = Field(description="Runs queued or going.")
    active_done: int = Field(description="Answers those runs have asked so far.")
    active_total: int = Field(description="Answers those runs ask for, in all.")
    last_run_status: (
        Literal["queued", "running", "stopping", "stopped", "done", "failed"] | None
    ) = Field(
        description="How its newest run stands: `failed` or `stopped` until it is resumed or "
        "another run starts. Empty before any run."
    )
    last_activity_at: datetime = Field(
        description="When something last happened on it: added, a run started, went or ended "
        "(failed too), labels set or cleared, or brought back from Settled."
    )
    settled: bool = Field(
        description="Listed apart as left alone: settled by an admin until something happens on "
        "it, or by itself after 24 hours of nothing (`auto_settle`). Never while a run goes."
    )
    auto_settle: bool | None = Field(
        description="Whether it settles by itself after 24 hours of nothing: its own choice, or "
        "empty to follow the organisation's (`GET /v1/settings`)."
    )


class Dataset(DatasetSummary):
    columns: list[Column] = Field(
        description="Every column of `data`: `__row_id`, the answer columns, newest first, then the "
        "file's own."
    )
    answers: list[AnswerColumn] = Field(description="What its answer columns are, newest first.")


class ColumnProfile(BaseModel):
    name: str
    type: str
    min: str | None
    max: str | None
    avg: str | None
    approx_unique: int | None
    null_percentage: float | None


def create_dataset(org_id: str, source: str, connection_id: str | None = None) -> Dataset:
    """Ingest a local file path, a public http(s) URL, or an `s3://bucket/key` object, read with the
    given connection or else the environment's AWS credentials."""
    if connections.is_s3(source):
        storage.check_not_storage(source)
        name = source.rstrip("/").rsplit("/", 1)[-1]
        return _ingest(
            org_id,
            source,
            name=name,
            source=source,
            readers=_S3_READERS,
            connection_id=connection_id,
        )
    if connection_id:
        raise InvalidRequest("A connection is only for s3:// sources.")
    if source.startswith(("http://", "https://")):
        return _download_dataset(org_id, source)
    if not config().server_files:
        raise InvalidRequest("Paths on the server can't be read here. Upload the file instead.")
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise InvalidRequest(f"File not found: {path}")
    if path.stat().st_size > config().max_file_bytes:
        raise InvalidRequest(_too_big(path.name))
    return _ingest_file(org_id, path, name=path.name, source=str(path))


def upload_dataset(org_id: str, file: BinaryIO, filename: str) -> Dataset:
    name = Path(filename).name
    with _temp_copy(file, name) as path:
        return _ingest_file(org_id, path, name=name, source=f"upload:{name}")


def detect_format(path: Path) -> tuple[Format, bool]:
    """The file's format and whether it is gzipped, from its content rather than its name."""
    with path.open("rb") as f:
        magic = f.read(4)
    if magic == b"PAR1":
        return "parquet", False
    gzipped = magic[:2] == b"\x1f\x8b"
    try:
        with gzip.open(path) if gzipped else path.open("rb") as f:
            sample = f.read(64 * 1024)
    except OSError as e:
        raise InvalidRequest(f"Could not decompress {path.name}: {e}") from e
    if b"\0" in sample:
        raise InvalidRequest(f"{path.name} is not a CSV, TSV, JSON, JSONL or Parquet file.")
    first = sample.removeprefix(b"\xef\xbb\xbf").lstrip()[:1]
    if not first:
        raise InvalidRequest(f"{path.name} is empty.")
    if first == b"[":
        return "json", gzipped
    if first == b"{":
        return "jsonl", gzipped
    return "csv", gzipped


def name_without_extension(filename: str) -> str:
    """`filename` without its data file extension, e.g. `events.jsonl.gz` → `events`."""
    name = filename[:-3] if filename.lower().endswith(".gz") else filename
    stem, extension = os.path.splitext(name)
    return (stem if extension.lower() in EXTENSIONS else name) or "dataset"


def _download_dataset(org_id: str, url: str) -> Dataset:
    name = Path(urlparse(url).path).name or "download"
    try:
        with network.open_url(url, timeout=60) as response:
            if response.headers.get_content_type() == "text/html":
                raise InvalidRequest(
                    f"{url} is a web page, not a data file. Use the link to the file itself."
                )
            with _temp_copy(response, name) as path:
                return _ingest_file(org_id, path, name=name, source=url)
    except HTTPError as e:
        raise InvalidRequest(f"Could not download {url}: HTTP {e.code} {e.reason}") from e
    except (URLError, TimeoutError) as e:
        reason = network.describe(getattr(e, "reason", e), urlparse(url).hostname)
        raise InvalidRequest(f"Could not download {url}: {reason}") from e


@contextmanager
def _temp_copy(file: BinaryIO, filename: str) -> Iterator[Path]:
    """Write `file` to a temporary file named `filename` for DuckDB to read."""
    tmp_dir = db.data_dir() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp_dir) as directory:
        path = Path(directory) / filename
        copied = 0
        with path.open("wb") as out:
            while chunk := file.read(1024 * 1024):
                copied += len(chunk)
                if copied > config().max_file_bytes:
                    raise InvalidRequest(_too_big(filename))
                out.write(chunk)
        yield path


def _too_big(name: str) -> str:
    return f"{name} is bigger than {_size(config().max_file_bytes)}, rowlab's limit (`ROWLAB_MAX_FILE`)."


def _size(size: int) -> str:
    """A size in bytes as people write it, e.g. `1 GB` or `500 MB`."""
    for unit, bytes_ in (("TB", 1000**4), ("GB", 1000**3), ("MB", 1000**2), ("KB", 1000)):
        if size >= bytes_:
            return f"{size / bytes_:g} {unit}"
    return f"{size} bytes"


# Objects in S3 are read where they are, so their content can't be looked at first: each reader is tried
# in turn, the strictest first. DuckDB decompresses `.gz` objects by their name.
_S3_READERS: list[tuple[Format, str]] = [
    ("parquet", "read_parquet(?)"),
    ("json", "read_json(?, format = 'auto')"),
    ("csv", "read_csv(?)"),
]


def _ingest_file(org_id: str, path: Path, *, name: str, source: str) -> Dataset:
    """Ingest a local file, read as the format its content shows."""
    fmt, gzipped = detect_format(path)
    reader = READERS[fmt].format(compression="gzip" if gzipped else "none")
    return _ingest(org_id, str(path), name=name, source=source, readers=[(fmt, reader)])


def _ingest(
    org_id: str,
    location: str,
    *,
    name: str,
    source: str,
    readers: list[tuple[Format, str]],
    connection_id: str | None = None,
) -> Dataset:
    """Copy a file into the dataset's `data.parquet` with a `__row_id`, and record it. The first of
    `readers` that can read it is used."""
    dataset_id = uuid.uuid4().hex
    storage.prepare(dataset_id)
    try:
        with storage.connect() as con:
            if connections.is_s3(location):
                connections.configure(con, org_id, connection_id)
                size = con.execute("SELECT size FROM read_blob(?)", [location]).fetchone()[0]
                if size > config().max_file_bytes:
                    raise InvalidRequest(_too_big(name))
                if size == 0:
                    raise InvalidRequest(f"{name} is empty.")
            for i, (_, reader) in enumerate(readers):
                try:
                    # A table keeps the file's row order, so `rowid` becomes a stable row id.
                    con.execute(f"CREATE TABLE src AS SELECT * FROM {reader}", [location])
                    break
                except (duckdb.HTTPException, duckdb.InterruptException):
                    raise
                except duckdb.Error as e:
                    if i == len(readers) - 1:
                        formats = " or ".join(fmt.upper() for fmt, _ in readers)
                        raise InvalidRequest(f"Could not read {name} as {formats}: {e}") from e
            columns = [Column(name=r[0], type=r[1]) for r in con.execute("DESCRIBE src").fetchall()]
            if any(c.name == ROW_ID for c in columns):
                raise InvalidRequest(f"The file already has a `{ROW_ID}` column.")
            storage.write(
                con,
                f"SELECT rowid AS {ROW_ID}, * FROM src ORDER BY rowid",
                storage.location(dataset_id, "data.parquet"),
            )
    except duckdb.HTTPException as e:
        storage.delete_dataset(dataset_id)
        status = f"HTTP {e.status_code} {e.reason}" if e.status_code else str(e)
        raise InvalidRequest(f"Could not read {source}: {status}") from e
    except duckdb.Error as e:
        storage.delete_dataset(dataset_id)
        raise InvalidRequest(f"Could not read {source}: {e}") from e
    except BaseException:
        storage.delete_dataset(dataset_id)
        raise

    return _register(dataset_id, org_id=org_id, name=name_without_extension(name), source=source)


class RenameDataset(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def rename_dataset(dataset_id: str, request: RenameDataset) -> Dataset:
    """Change a display name without changing its data, lineage or descendants' names."""
    name = request.name.strip()
    if not name:
        raise InvalidRequest("Give the dataset a name.")
    get_dataset(dataset_id)
    with db.connect() as conn:
        conn.execute("UPDATE datasets SET name = ? WHERE id = ?", (name, dataset_id))
    return get_dataset(dataset_id)


# Settling: a dataset nothing has happened on for this long settles by itself, unless that is off for
# it or its organisation (`settings` key `AUTO_SETTLE`, on unless set to "0").
SETTLE_AFTER = timedelta(hours=24)
AUTO_SETTLE = "auto_settle"


class Settling(BaseModel):
    settled: bool | None = Field(
        default=None,
        description="Settle it, or bring it back: then it settles by itself again only after "
        "another 24 hours of nothing. Left out, unchanged.",
    )
    auto_settle: Literal["organisation", "on", "off"] | None = Field(
        default=None,
        description="Whether it settles by itself after 24 hours of nothing: as the organisation "
        "says, or on or off for it alone. Left out, unchanged.",
    )


def settle_dataset(dataset_id: str, request: Settling) -> Dataset:
    """Settle a dataset or bring it back, or choose whether it settles by itself."""
    dataset = get_dataset(dataset_id)
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        if request.settled:
            if dataset.active_runs:
                raise InvalidRequest("It has runs going: settle it once they end.")
            conn.execute("UPDATE datasets SET settled_at = ? WHERE id = ?", (now, dataset_id))
        elif request.settled is False:
            conn.execute(
                "UPDATE datasets SET settled_at = NULL, unsettled_at = ? WHERE id = ?",
                (now, dataset_id),
            )
        if request.auto_settle is not None:
            auto = {"organisation": None, "on": 1, "off": 0}[request.auto_settle]
            conn.execute("UPDATE datasets SET auto_settle = ? WHERE id = ?", (auto, dataset_id))
    return get_dataset(dataset_id)


def auto_settle(org_id: str) -> bool:
    """Whether the organisation's datasets settle by themselves, unless one says otherwise."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE org_id = ? AND key = ?", (org_id, AUTO_SETTLE)
        ).fetchone()
    return row is None or row["value"] != "0"


def set_auto_settle(org_id: str, on: bool) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (org_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (org_id, key) DO UPDATE SET value = excluded.value",
            (org_id, AUTO_SETTLE, "1" if on else "0"),
        )


def _settling(row: Any, auto_default: bool, now: datetime) -> dict[str, Any]:
    """A dataset row with when it was last active and whether it is settled."""
    times = (row["created_at"], row["last_run_at"], row["labelled_at"], row["unsettled_at"])
    last = max(datetime.fromisoformat(t) for t in times if t)
    settled_at = datetime.fromisoformat(row["settled_at"]) if row["settled_at"] else None
    auto = None if row["auto_settle"] is None else bool(row["auto_settle"])
    settled = not row["active_runs"] and (
        (settled_at is not None and settled_at >= last)
        or ((auto_default if auto is None else auto) and last < now - SETTLE_AFTER)
    )
    return {**row, "last_activity_at": last, "settled": settled, "auto_settle": auto}


def _register(dataset_id: str, *, org_id: str, name: str, source: str) -> Dataset:
    """Record a dataset whose file has been written."""
    file = storage.location(dataset_id, "data.parquet")
    with storage.connect() as con:
        columns = [
            Column(name=r[0], type=r[1])
            for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet({sql_string(file)})"
            ).fetchall()
        ]
        row_count = con.execute(
            f"SELECT count(*) FROM read_parquet({sql_string(file)})"
        ).fetchone()[0]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO datasets (id, org_id, name, source, row_count, size_bytes, columns,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dataset_id,
                org_id,
                name,
                source,
                row_count,
                storage.size(file),
                json.dumps([c.model_dump() for c in columns]),
                datetime.now(UTC).isoformat(),
            ),
        )
    return get_dataset(dataset_id)


def list_datasets(org_id: str) -> list[DatasetSummary]:
    """The organisation's datasets, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT d.*, {_SUMMARY} FROM datasets d WHERE d.org_id = ? ORDER BY d.created_at DESC",
            (org_id,),
        ).fetchall()
    auto_default, now = auto_settle(org_id), datetime.now(UTC)
    return [DatasetSummary(**_settling(row, auto_default, now)) for row in rows]


def get_dataset(dataset_id: str) -> Dataset:
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT d.*, {_SUMMARY} FROM datasets d WHERE d.id = ?", (dataset_id,)
        ).fetchone()
    if row is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    with storage.connect() as con:
        attach(con, dataset_id, empty=True)
        columns = [Column(name=r[0], type=r[1]) for r in con.execute("DESCRIBE data").fetchall()]
    found = _settling(row, auto_settle(row["org_id"]), datetime.now(UTC))
    return Dataset(**{**found, "columns": columns}, answers=answer_columns(dataset_id))


# Statuses of a run that still has work to do, and as SQL.
ACTIVE = ("queued", "running", "stopping")
_ACTIVE = "('queued', 'running', 'stopping')"

# What a dataset's summary says of its answers, runs and activity, for `SELECT d.*, … FROM datasets d`.
_SUMMARY = f"""
    (SELECT count(*) FROM answer_columns a WHERE a.dataset_id = d.id) AS answer_columns,
    (SELECT count(*) FROM runs r WHERE r.dataset_id = d.id AND r.status IN {_ACTIVE}) AS active_runs,
    (SELECT coalesce(sum(r.done + r.chunk_done), 0) FROM runs r
        WHERE r.dataset_id = d.id AND r.status IN {_ACTIVE}) AS active_done,
    (SELECT coalesce(sum(r.total), 0) FROM runs r
        WHERE r.dataset_id = d.id AND r.status IN {_ACTIVE}) AS active_total,
    (SELECT r.status FROM runs r WHERE r.dataset_id = d.id
        ORDER BY r.created_at DESC LIMIT 1) AS last_run_status,
    (SELECT max(coalesce(r.updated_at, r.created_at)) FROM runs r
        WHERE r.dataset_id = d.id) AS last_run_at
"""


def org_of(dataset_id: str) -> str:
    """The organisation a dataset belongs to."""
    with db.connect() as conn:
        row = conn.execute("SELECT org_id FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    return row["org_id"]


def check_access(org_id: str, dataset_id: str) -> None:
    """Raise NotFound unless the dataset is the organisation's: others' are as good as missing."""
    if org_of(dataset_id) != org_id:
        raise NotFound(f"Dataset {dataset_id} not found")


def delete_dataset(dataset_id: str) -> None:
    """Delete a dataset with its answers and runs. A run under way stops at its next check."""
    get_dataset(dataset_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    storage.delete_dataset(dataset_id)


# Answer columns


def answer_columns(dataset_id: str) -> list[AnswerColumn]:
    """What the dataset's answer columns are, newest first, with how many rows have an answer and
    what runs spent on them."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT a.name, a.model, a.task, a.answered, a.created_at,"
            " (SELECT count(*) FROM labels l WHERE l.dataset_id = a.dataset_id AND l.name = a.name"
            "  AND a.model = '') AS labelled"
            " FROM answer_columns a WHERE a.dataset_id = ? ORDER BY a.created_at DESC, a.name, a.model",
            (dataset_id,),
        ).fetchall()
        runs = conn.execute(
            "SELECT config, costs, created_at FROM runs WHERE dataset_id = ?", (dataset_id,)
        ).fetchall()
    found = []
    for row in rows:
        task = Task.model_validate_json(row["task"])
        model = row["model"] or None
        cost = 0.0
        for run in runs:
            if run["created_at"] < row["created_at"]:
                continue  # From before the column was deleted and asked anew.
            columns = {t["id"]: t["column"] for t in json.loads(run["config"])["tasks"]}
            cost += sum(
                c["cost"]
                for c in json.loads(run["costs"])
                if columns.get(c["task_id"]) == row["name"] and c["model"] == model
            )
        answer = AnswerColumn(
            name=row["name"],
            model=model,
            task=task,
            columns=[],
            answered=row["labelled"] if model is None else row["answered"],
            cost=cost,
        )
        answer.columns = [name for name, _ in _columns(answer)]
        found.append(answer)
    return found


def _columns(answer: AnswerColumn) -> list[tuple[str, str]]:
    """An answer column's columns in `data`, with their SQL types."""
    if answer.model is None:
        return tasks.label_columns(answer.task)
    return tasks.columns(answer.task, answer.model)


def definition(task: Task) -> dict[str, Any]:
    """What a task asks, without what doesn't change its answers' meaning: its id, models and preset."""
    return task.model_dump(mode="json", exclude={"id", "models", "preset"})


def check_answers(dataset_id: str, task: Task, models: list[str | None]) -> None:
    """Raise InvalidRequest unless the task's answers from `models` (None for labels) can go in the
    dataset: a name in use answers the same question, and new columns don't take a name in use."""
    existing = {(a.name, a.model): a for a in answer_columns(dataset_id)}
    taken = {c["name"] for c in _own_columns(dataset_id)}
    for answer in existing.values():
        taken |= set(answer.columns)
    for model in models:
        found = existing.get((task.column, model))
        if found is not None:
            if definition(found.task) != definition(task):
                who = f"from {tasks.model_slug(model)}" if model else "set by people"
                raise InvalidRequest(
                    f"The dataset already has answers {who} in `{task.column}`, to a different "
                    f"question. Name the column differently, e.g. `{_free(task.column, existing)}`."
                )
            continue
        new = AnswerColumn(name=task.column, model=model, task=task, columns=[], answered=0, cost=0)
        clash = sorted({name for name, _ in _columns(new)} & taken)
        if clash:
            raise InvalidRequest(
                f"The dataset already has a column {', '.join(clash)}. Name the task's column "
                "differently."
            )


def _free(name: str, existing: dict) -> str:
    """A name like `name` that no answer column has."""
    names = {n for n, _ in existing}
    n = 2
    while f"{name}_{n}" in names:
        n += 1
    return f"{name}_{n}"


def add_answers(conn: db.Connection, dataset_id: str, task: Task, model: str | None) -> None:
    """Record the task's answers from `model` (None for labels), unless the dataset has them: in
    the transaction that starts the run or saves the labels. `check_answers` first."""
    conn.execute(
        "INSERT INTO answer_columns (dataset_id, name, model, task, created_at)"
        " VALUES (?, ?, ?, ?, ?) ON CONFLICT (dataset_id, name, model) DO NOTHING",
        (
            dataset_id,
            task.column,
            model or "",
            task.model_copy(update={"models": []}).model_dump_json(),
            datetime.now(UTC).isoformat(),
        ),
    )


def delete_answers(dataset_id: str, name: str, model: str | None) -> None:
    """Delete a task's answers from a model, or its labels. Model replies are kept, so asking the
    same again is free. A run still asking for them must be stopped first."""
    with db.connect() as conn:
        lock(conn, dataset_id)
        found = conn.execute(
            "SELECT 1 FROM answer_columns WHERE dataset_id = ? AND name = ? AND model = ?",
            (dataset_id, name, model or ""),
        ).fetchone()
        if found is None:
            raise NotFound(f"No answers in `{name}`" + (f" from {model}" if model else "") + ".")
        if model is not None:
            for run in conn.execute(
                f"SELECT config FROM runs WHERE dataset_id = ? AND status IN {_ACTIVE}",
                (dataset_id,),
            ).fetchall():
                if any(
                    t["column"] == name and model in t["models"]
                    for t in json.loads(run["config"])["tasks"]
                ):
                    raise InvalidRequest("A run is still asking for these answers. Stop it first.")
        conn.execute(
            "DELETE FROM answer_columns WHERE dataset_id = ? AND name = ? AND model = ?",
            (dataset_id, name, model or ""),
        )
        if model is None:
            conn.execute("DELETE FROM labels WHERE dataset_id = ? AND name = ?", (dataset_id, name))
            conn.execute(
                "UPDATE datasets SET labelled_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), dataset_id),
            )


def lock(conn: db.Connection, dataset_id: str) -> None:
    """Hold the dataset's row until the transaction ends, so starting runs and saving labels go one
    at a time per dataset."""
    if conn.execute("UPDATE datasets SET name = name WHERE id = ?", (dataset_id,)).rowcount == 0:
        raise NotFound(f"Dataset {dataset_id} not found")


def _own_columns(dataset_id: str) -> list[dict[str, str]]:
    with db.connect() as conn:
        row = conn.execute("SELECT columns FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    return json.loads(row["columns"])


# The table `data`


def run_files(dataset_id: str, run_id: str, status: str, chunks: int) -> list[str]:
    """The files a run has written its answers to: one per chunk while it goes, then one."""
    if not chunks:
        return []
    if status in ACTIVE:
        return [run_part(dataset_id, run_id, k) for k in range(chunks)]
    return [storage.location(dataset_id, "runs", f"{run_id}.parquet")]


def run_part(dataset_id: str, run_id: str, chunk: int) -> str:
    return storage.location(dataset_id, "runs", run_id, f"part-{chunk:06d}.parquet")


def attach(con: duckdb.DuckDBPyConnection, dataset_id: str, *, empty: bool = False) -> None:
    """Make the dataset the view `data` on a DuckDB connection: its file's rows, each answer column
    from the runs that wrote it (a run only writes cells that were empty, so they never overlap),
    and labels people set, loaded into a temporary table. The answer columns come right after
    `__row_id`, newest first.

    `empty` leaves the answer columns without their values, typed NULLs: the dataset's columns
    and their types, without reading its runs' files (one per run, which on a dataset with many
    runs takes seconds)."""
    _own_columns(dataset_id)  # Raises NotFound.
    answers = answer_columns(dataset_id)
    data = sql_string(storage.location(dataset_id, "data.parquet"))
    if empty:
        select = [f"d.{ROW_ID}"] + [
            f"NULL::{type_} AS {sql_ident(name)}" for a in answers for name, type_ in _columns(a)
        ]
        con.execute(
            f"CREATE VIEW data AS SELECT {', '.join(select)}, d.* EXCLUDE ({ROW_ID})"
            f" FROM read_parquet({data}) AS d"
        )
        return
    with db.connect() as conn:
        runs = conn.execute(
            "SELECT id, status, next_chunk, config, created_at FROM runs WHERE dataset_id = ?"
            " ORDER BY created_at",
            (dataset_id,),
        ).fetchall()
        labels = conn.execute(
            "SELECT name, row_id, value FROM labels WHERE dataset_id = ?", (dataset_id,)
        ).fetchall()
        created = {
            (r["name"], r["model"] or None): r["created_at"]
            for r in conn.execute(
                "SELECT name, model, created_at FROM answer_columns WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchall()
        }

    joins = []
    writers: dict[str, list[str]] = {}  # A column's runs, by their alias.
    for i, run in enumerate(runs):
        files = run_files(dataset_id, run["id"], run["status"], run["next_chunk"])
        if not files:
            continue
        alias = f"r{i}"
        joins.append(
            f"LEFT JOIN read_parquet([{', '.join(map(sql_string, files))}]) AS {alias}"
            f" USING ({ROW_ID})"
        )
        for task in json.loads(run["config"])["tasks"]:
            task = Task.model_validate(task)
            for model in task.models:
                since = created.get((task.column, model))
                # Answers deleted since are left out.
                if since is not None and run["created_at"] >= since:
                    for name, _ in tasks.columns(task, model):
                        writers.setdefault(name, []).append(alias)

    by_label: dict[str, list] = {}
    for row in labels:
        by_label.setdefault(row["name"], []).append(row)
    select = [f"d.{ROW_ID}"]
    for n, answer in enumerate(answers):
        if answer.model is None:
            table = f"labels_{n}"
            columns = tasks.label_columns(answer.task)
            con.execute(
                f"CREATE TEMPORARY TABLE {table} ({ROW_ID} BIGINT, "
                + ", ".join(f"{sql_ident(c)} {t}" for c, t in columns)
                + ")"
            )
            values = [
                [row["row_id"], *tasks.read_label(answer.task, json.loads(row["value"])).values()]
                for row in by_label.get(answer.name, [])
            ]
            if values:
                con.executemany(
                    f"INSERT INTO {table} VALUES ({', '.join('?' * (len(columns) + 1))})", values
                )
            joins.append(f"LEFT JOIN {table} USING ({ROW_ID})")
            select += [f"{table}.{sql_ident(c)}" for c, _ in columns]
            continue
        for name, type_ in _columns(answer):
            found = [f"{alias}.{sql_ident(name)}" for alias in writers.get(name, [])]
            value = (
                found[0]
                if len(found) == 1
                else f"coalesce({', '.join(found)})"
                if found
                else f"NULL::{type_}"
            )
            select.append(f"{value} AS {sql_ident(name)}")
    con.execute(
        f"CREATE VIEW data AS SELECT {', '.join(select)}, d.* EXCLUDE ({ROW_ID})"
        f" FROM read_parquet({data}) AS d {' '.join(joins)}"
    )


def dataset_fields(dataset_id: str) -> dict[str, tuple[str, list[str]]]:
    """Every column and every path into struct columns, in column order.

    Maps the path, e.g. `actor.login`, to its type and the keys leading to it in a row,
    e.g. `["actor", "login"]`. Keys may contain dots themselves; the path is only for display.
    """
    with storage.connect() as con:
        attach(con, dataset_id, empty=True)
        relation = con.sql(f"SELECT * EXCLUDE ({ROW_ID}) FROM data")
        columns = list(zip(relation.columns, relation.types))
    fields: dict[str, tuple[str, list[str]]] = {}

    def add(keys: list[str], type_: duckdb.sqltypes.DuckDBPyType) -> None:
        fields.setdefault(".".join(keys), (str(type_), keys))
        if type_.id == "struct":
            for name, child in type_.children:
                add([*keys, name], child)

    for name, type_ in columns:
        add([name], type_)
    return fields


def profile_dataset(dataset_id: str) -> list[ColumnProfile]:
    """Type, range, average, approximate distinct count and share of nulls for every column and
    every path into struct columns (e.g. `actor.login`)."""
    get_dataset(dataset_id)
    select = ", ".join(
        "t." + ".".join(sql_ident(k) for k in keys) + f" AS {sql_ident(path)}"
        for path, (_, keys) in dataset_fields(dataset_id).items()
    )
    with storage.connect() as con:
        attach(con, dataset_id)
        rows = con.execute(f"SUMMARIZE SELECT {select} FROM data AS t")
        summary = [dict(zip([d[0] for d in rows.description], r)) for r in rows.fetchall()]
    return [
        ColumnProfile(
            name=s["column_name"],
            type=s["column_type"],
            min=s["min"],
            max=s["max"],
            avg=None if s["avg"] is None else str(s["avg"]),
            approx_unique=s["approx_unique"],
            null_percentage=None if s["null_percentage"] is None else float(s["null_percentage"]),
        )
        for s in summary
    ]
