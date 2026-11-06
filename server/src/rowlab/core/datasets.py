"""Datasets: files ingested once into Parquet with a stable `__row_id`, then explored with DuckDB."""

import gzip
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import duckdb
import duckdb.sqltypes
from pydantic import BaseModel, Field

from rowlab import __version__
from rowlab.core import db
from rowlab.core.errors import InvalidRequest, NotFound

ROW_ID = "__row_id"

Format = Literal["csv", "json", "jsonl", "parquet"]

# Accepted name extensions per format. The first is added to names that lack a matching one.
EXTENSIONS: dict[Format, tuple[str, ...]] = {
    "csv": (".csv", ".tsv"),
    "json": (".json",),
    "jsonl": (".jsonl", ".ndjson"),
    "parquet": (".parquet",),
}

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


class RunProgress(BaseModel):
    run_id: str
    number: int
    done: int = Field(description="Model calls answered so far.")
    total: int = Field(description="Model calls the run makes.")


class Dataset(BaseModel):
    id: str
    name: str
    source: str
    format: Format
    row_count: int
    size_bytes: int
    columns: list[Column]
    created_at: datetime
    last_activity_at: datetime = Field(
        description="When it was added or last run, whichever is later."
    )
    running: RunProgress | None = Field(description="Its latest run, while that is running.")


class ColumnProfile(BaseModel):
    name: str
    type: str
    min: str | None
    max: str | None
    avg: str | None
    approx_unique: int | None
    null_percentage: float | None


class Filter(BaseModel):
    column: str
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "is_null", "is_not_null"]
    value: str | int | float | bool | None = None


class Sort(BaseModel):
    column: str
    desc: bool = False


class RowSelection(BaseModel):
    search: str = Field("", description="Case-insensitive text match against any column.")
    filters: list[Filter] = []


class Scope(RowSelection):
    """Which rows, in which order: what the rows table shows and what a job runs on."""

    sort: list[Sort] = Field([], description=f"Ties and the default order are by `{ROW_ID}`.")
    limit: int | None = Field(None, ge=1, description="Only the first rows, in this order.")


class Query(Scope):
    """A page of a scope's rows."""

    offset: int = Field(0, ge=0)
    page_size: int = Field(100, ge=1, le=1000)


class QueryResult(BaseModel):
    total: int = Field(description="Rows in the scope, ignoring paging.")
    matched: int = Field(description="Rows matching the search and filters, ignoring the limit.")
    rows: list[dict[str, Any]]


def create_dataset(source: str) -> Dataset:
    """Ingest a local file path or a public http(s) URL."""
    if source.startswith(("http://", "https://")):
        return _download_dataset(source)
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise InvalidRequest(f"File not found: {path}")
    return _ingest(path, name=path.name, source=str(path))


def upload_dataset(file: BinaryIO, filename: str) -> Dataset:
    name = Path(filename).name
    with _temp_copy(file, name) as path:
        return _ingest(path, name=name, source=f"upload:{name}")


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
    if first == b"[":
        return "json", gzipped
    if first == b"{":
        return "jsonl", gzipped
    return "csv", gzipped


def name_with_extension(filename: str, fmt: Format, gzipped: bool) -> str:
    """`filename` with its extension added or replaced to match the content.

    E.g. `comments` → `comments.json`, `export.txt` → `export.csv`, `events` → `events.jsonl.gz`.
    """
    name = filename[:-3] if filename.lower().endswith(".gz") else filename
    stem, extension = os.path.splitext(name)
    if extension.lower() not in EXTENSIONS[fmt]:
        name = stem + EXTENSIONS[fmt][0]
    return name + ".gz" if gzipped else name


def _download_dataset(url: str) -> Dataset:
    name = Path(urlparse(url).path).name or "download"
    # Some hosts reject Python's default user agent.
    request = Request(url, headers={"User-Agent": f"rowlab/{__version__}"})
    try:
        with urlopen(request, timeout=60) as response, _temp_copy(response, name) as path:
            return _ingest(path, name=name, source=url)
    except HTTPError as e:
        raise InvalidRequest(f"Could not download {url}: HTTP {e.code} {e.reason}") from e
    except (URLError, TimeoutError) as e:
        raise InvalidRequest(f"Could not download {url}: {getattr(e, 'reason', e)}") from e


@contextmanager
def _temp_copy(file: BinaryIO, filename: str) -> Iterator[Path]:
    """Write `file` to a temporary file named `filename` for DuckDB to read."""
    tmp_dir = db.data_dir() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp_dir) as directory:
        path = Path(directory) / filename
        with path.open("wb") as out:
            shutil.copyfileobj(file, out)
        yield path


def _ingest(path: Path, *, name: str, source: str) -> Dataset:
    """Copy a local file into `datasets/{id}/data.parquet` with a `__row_id`, and record it."""
    fmt, gzipped = detect_format(path)
    name = name_with_extension(name, fmt, gzipped)
    reader = READERS[fmt].format(compression="gzip" if gzipped else "none")
    dataset_id = uuid.uuid4().hex
    directory = _dataset_dir(dataset_id)
    directory.mkdir(parents=True)
    try:
        with duckdb.connect() as con:
            con.execute("SET temp_directory = ?", [str(db.data_dir() / "tmp")])
            # A table keeps the file's row order, so `rowid` becomes a stable row id.
            con.execute(f"CREATE TABLE src AS SELECT * FROM {reader}", [str(path)])
            columns = [Column(name=r[0], type=r[1]) for r in con.execute("DESCRIBE src").fetchall()]
            if any(c.name == ROW_ID for c in columns):
                raise InvalidRequest(f"The file already has a `{ROW_ID}` column.")
            row_count = con.execute("SELECT count(*) FROM src").fetchone()[0]
            con.execute(
                f"COPY (SELECT rowid AS {ROW_ID}, * FROM src ORDER BY rowid) "
                f"TO {_sql_string(directory / 'data.parquet')} (FORMAT parquet)"
            )
    except duckdb.Error as e:
        shutil.rmtree(directory)
        raise InvalidRequest(f"Could not read {name} as {fmt.upper()}: {e}") from e
    except BaseException:
        shutil.rmtree(directory)
        raise

    now = datetime.now(UTC)
    dataset = Dataset(
        id=dataset_id,
        name=name,
        source=source,
        format=fmt,
        row_count=row_count,
        size_bytes=(directory / "data.parquet").stat().st_size,
        columns=[Column(name=ROW_ID, type="BIGINT"), *columns],
        created_at=now,
        last_activity_at=now,
        running=None,
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO datasets (id, name, source, format, row_count, size_bytes, columns,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dataset.id,
                dataset.name,
                dataset.source,
                dataset.format,
                dataset.row_count,
                dataset.size_bytes,
                json.dumps([c.model_dump() for c in dataset.columns]),
                dataset.created_at.isoformat(),
            ),
        )
    return dataset


# Datasets with their latest activity and the progress of a running run. Timestamps are ISO 8601 in
# UTC, so they compare as text.
_SELECT = """
SELECT d.*,
    max(d.created_at, coalesce((SELECT max(r.created_at) FROM runs r WHERE r.dataset_id = d.id), ''))
        AS last_activity_at,
    (SELECT json_object('run_id', r.id, 'number', r.number, 'done', r.done, 'total', r.total)
        FROM runs r WHERE r.dataset_id = d.id AND r.status = 'running'
        ORDER BY r.number DESC LIMIT 1) AS running
FROM datasets d
"""


def list_datasets() -> list[Dataset]:
    """Every dataset, the most recently added or run first."""
    with db.connect() as conn:
        rows = conn.execute(f"{_SELECT} ORDER BY last_activity_at DESC").fetchall()
    return [_from_row(row) for row in rows]


def get_dataset(dataset_id: str) -> Dataset:
    with db.connect() as conn:
        row = conn.execute(f"{_SELECT} WHERE d.id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    return _from_row(row)


def delete_dataset(dataset_id: str) -> None:
    get_dataset(dataset_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    shutil.rmtree(_dataset_dir(dataset_id), ignore_errors=True)


def dataset_fields(dataset_id: str) -> dict[str, tuple[str, list[str]]]:
    """Every column and every path into struct columns, in column order.

    Maps the path, e.g. `actor.login`, to its type and the keys leading to it in a row,
    e.g. `["actor", "login"]`. Keys may contain dots themselves; the path is only for display.
    """
    with duckdb.connect() as con:
        relation = con.sql(f"SELECT * EXCLUDE ({ROW_ID}) FROM {parquet_source(dataset_id)}")
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
        "t." + ".".join(_ident(k) for k in keys) + f" AS {_ident(path)}"
        for path, (_, keys) in dataset_fields(dataset_id).items()
    )
    with duckdb.connect() as con:
        rows = con.execute(f"SUMMARIZE SELECT {select} FROM {parquet_source(dataset_id)} AS t")
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


def query_dataset(dataset_id: str, query: Query) -> QueryResult:
    """One page of a scope's rows: matching the search and filters, in order, up to the limit."""
    types = _column_types(dataset_id)
    where, params = _where(query, types)
    order = [
        f"{_ident(_check_column(s.column, types))} {'DESC' if s.desc else 'ASC'} NULLS LAST"
        for s in query.sort
    ]
    order.append(ROW_ID)

    sql_from = f"FROM {parquet_source(dataset_id)} AS t WHERE {where}"
    try:
        with duckdb.connect() as con:
            matched = con.execute(f"SELECT count(*) {sql_from}", params).fetchone()[0]
            total = min(matched, query.limit) if query.limit else matched
            size = max(0, min(query.page_size, total - query.offset))
            rows = con.execute(
                f"SELECT to_json(t) {sql_from} ORDER BY {', '.join(order)} LIMIT ? OFFSET ?",
                [*params, size, query.offset],
            ).fetchall()
    except duckdb.ConversionException as e:
        raise InvalidRequest(f"Invalid filter value: {e}") from e
    return QueryResult(total=total, matched=matched, rows=[json.loads(r[0]) for r in rows])


def sample_rows(dataset_id: str, n: int, selection: RowSelection) -> list[dict[str, Any]]:
    """Up to `n` of the selected rows, picked at random, the same ones on every call."""
    where, params = _where(selection, _column_types(dataset_id))
    try:
        with duckdb.connect() as con:
            # Sampling a subquery, because DuckDB samples before applying a WHERE clause.
            rows = con.execute(
                f"SELECT to_json(t) FROM (SELECT * FROM {parquet_source(dataset_id)} "
                f"WHERE {where}) AS t USING SAMPLE reservoir({int(n)} ROWS) REPEATABLE (1)",
                params,
            ).fetchall()
    except duckdb.ConversionException as e:
        raise InvalidRequest(f"Invalid filter value: {e}") from e
    return [json.loads(r[0]) for r in rows]


def _where(selection: RowSelection, types: dict[str, str]) -> tuple[str, list[Any]]:
    """A SQL condition, with its parameters, for the rows a selection matches."""
    where, params = ["true"], []
    if selection.search:
        searchable = [_ident(c) for c in types if c != ROW_ID]
        where.append(
            "(" + " OR ".join(f"contains(lower(CAST({c} AS VARCHAR)), ?)" for c in searchable) + ")"
        )
        params += [selection.search.lower()] * len(searchable)
    for f in selection.filters:
        column = _ident(_check_column(f.column, types))
        if f.op == "is_null":
            where.append(f"{column} IS NULL")
        elif f.op == "is_not_null":
            where.append(f"{column} IS NOT NULL")
        elif f.op == "contains":
            where.append(f"contains(lower(CAST({column} AS VARCHAR)), ?)")
            params.append(str(f.value or "").lower())
        else:
            operator = _OPERATORS[f.op]
            where.append(f"{column} {operator} CAST(? AS {types[f.column]})")
            params.append(f.value)
    return " AND ".join(where), params


def _column_types(dataset_id: str) -> dict[str, str]:
    return {c.name: c.type for c in get_dataset(dataset_id).columns}


_OPERATORS = {
    "eq": "=",
    "ne": "IS DISTINCT FROM",
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
}


def _check_column(name: str, types: dict[str, str]) -> str:
    if name not in types:
        raise InvalidRequest(f"Unknown column: {name}")
    return name


def _from_row(row: sqlite3.Row) -> Dataset:
    running = json.loads(row["running"]) if row["running"] else None
    return Dataset(**{**dict(row), "columns": json.loads(row["columns"]), "running": running})


def _dataset_dir(dataset_id: str) -> Path:
    return db.data_dir() / "datasets" / dataset_id


def parquet_source(dataset_id: str) -> str:
    """A DuckDB table expression for a dataset's rows."""
    return f"read_parquet({_sql_string(_dataset_dir(dataset_id) / 'data.parquet')})"


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_string(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"
