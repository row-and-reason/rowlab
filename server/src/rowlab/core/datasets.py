"""Datasets: files ingested once into Parquet with a stable `__row_id`, then explored with DuckDB.

A run makes a new dataset: every row of the parent, with the run's answer columns added, empty for rows
outside the run's scope. While the run is under way, that dataset is read from its rows (`rows.parquet`,
a copy of the parent's) joined with the answers written so far (`parts/*.parquet`, one file per chunk);
`asked.parquet` lists the rows the run asks about. When the run finishes, the two are written out once as
`data.parquet`, like any other dataset.
"""

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


class DatasetRun(BaseModel):
    """The run that makes a dataset."""

    id: str
    status: Literal["queued", "running", "stopping", "stopped", "done", "failed"]
    done: int = Field(description="Model calls answered so far.")
    total: int = Field(description="Model calls the run makes.")


class Dataset(BaseModel):
    id: str
    name: str
    source: str
    row_count: int
    size_bytes: int
    columns: list[Column]
    created_at: datetime
    parent_id: str | None = Field(description="The dataset it was made from by a run.")
    branch: str | None = Field(
        description="Its place in the tree, e.g. `1.2`: the 2nd made from the 1st made from a file. "
        "Empty for a dataset added from a file."
    )
    run: DatasetRun | None = Field(
        description="The run that makes it; its rows fill in as it goes."
    )


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


def name_without_extension(filename: str) -> str:
    """`filename` without its data file extension, e.g. `events.jsonl.gz` → `events`."""
    name = filename[:-3] if filename.lower().endswith(".gz") else filename
    stem, extension = os.path.splitext(name)
    return (stem if extension.lower() in EXTENSIONS else name) or "dataset"


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
            con.execute(
                f"COPY (SELECT rowid AS {ROW_ID}, * FROM src ORDER BY rowid) "
                f"TO {sql_string(directory / 'data.parquet')} (FORMAT parquet)"
            )
    except duckdb.Error as e:
        shutil.rmtree(directory)
        raise InvalidRequest(f"Could not read {name} as {fmt.upper()}: {e}") from e
    except BaseException:
        shutil.rmtree(directory)
        raise

    return _register(dataset_id, name=name_without_extension(name), source=source)


def write_run_rows(parent_id: str, scope: Scope) -> tuple[str, int]:
    """Start the dataset a run makes: copy the parent's rows, so it doesn't depend on the parent, and
    list the ones in the run's scope. Returns its id and how many rows the run asks about; it is
    recorded once the run's first (empty) part is written."""
    types = _column_types(parent_id)
    where, params = _where(scope, types)
    limit = f"LIMIT {int(scope.limit)}" if scope.limit else ""
    dataset_id = uuid.uuid4().hex
    directory = _dataset_dir(dataset_id)
    run_parts_dir(dataset_id).mkdir(parents=True)
    try:
        with duckdb.connect() as con:
            con.execute(
                f"COPY (SELECT * FROM {dataset_source(parent_id)}) "
                f"TO {sql_string(directory / 'rows.parquet')} (FORMAT parquet)"
            )
            con.execute(
                f"COPY (SELECT {ROW_ID} FROM {dataset_source(parent_id)} AS t WHERE {where} "
                f"ORDER BY {_order(scope.sort, types)} {limit}) "
                f"TO {sql_string(directory / 'asked.parquet')} (FORMAT parquet)",
                params,
            )
            asked = con.execute(
                f"SELECT count(*) FROM read_parquet({sql_string(directory / 'asked.parquet')})"
            ).fetchone()[0]
    except BaseException:
        shutil.rmtree(directory)
        raise
    return dataset_id, asked


def register_run_dataset(dataset_id: str, parent_id: str) -> Dataset:
    """Record the dataset a run makes, once its rows and first (empty) part are written. It is named
    after its branch, numbered like an outline: `titanic__1` for the first made from `titanic`,
    `titanic__1.2` for the second made from `titanic__1`. Numbers aren't reused, so a name always
    means one dataset."""
    parent = get_dataset(parent_id)
    with db.connect() as conn:
        made = conn.execute(
            "UPDATE datasets SET made = made + 1 WHERE id = ? RETURNING made", (parent_id,)
        ).fetchone()[0]
    branch = f"{parent.branch}.{made}" if parent.branch else str(made)
    base = parent.name.removesuffix(f"__{parent.branch}") if parent.branch else parent.name
    return _register(
        dataset_id,
        name=f"{base}__{branch}",
        source=f"Made from {parent.name}",
        parent_id=parent_id,
        branch=branch,
    )


def finish_run_dataset(dataset_id: str) -> None:
    """Write a run's dataset out as one Parquet file, once every chunk is written."""
    directory = _dataset_dir(dataset_id)
    temporary = directory / "data.parquet.tmp"
    with duckdb.connect() as con:
        con.execute(
            f"COPY (SELECT * FROM {dataset_source(dataset_id)} ORDER BY {ROW_ID}) "
            f"TO {sql_string(temporary)} (FORMAT parquet)"
        )
    os.replace(temporary, directory / "data.parquet")
    (directory / "rows.parquet").unlink()
    (directory / "asked.parquet").unlink()
    shutil.rmtree(run_parts_dir(dataset_id))
    with db.connect() as conn:
        conn.execute(
            "UPDATE datasets SET size_bytes = ? WHERE id = ?",
            ((directory / "data.parquet").stat().st_size, dataset_id),
        )


def read_run_rows(dataset_id: str, *, offset: int, limit: int) -> list[dict[str, Any]]:
    """The rows a run asks about, by `__row_id`, without their answers."""
    directory = _dataset_dir(dataset_id)
    rows_file = sql_string(directory / "rows.parquet")
    asked_file = sql_string(directory / "asked.parquet")
    with duckdb.connect() as con:
        rows = con.execute(
            f"SELECT to_json(t) FROM read_parquet({rows_file}) AS t "
            f"SEMI JOIN read_parquet({asked_file}) AS a USING ({ROW_ID}) ORDER BY {ROW_ID} "
            "LIMIT ? OFFSET ?",
            [limit, offset],
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def run_parts_dir(dataset_id: str) -> Path:
    """Where the run making a dataset writes its answers, one Parquet file per chunk of rows."""
    return _dataset_dir(dataset_id) / "parts"


def _register(
    dataset_id: str,
    *,
    name: str,
    source: str,
    parent_id: str | None = None,
    branch: str | None = None,
) -> Dataset:
    """Record a dataset whose files have been written."""
    directory = _dataset_dir(dataset_id)
    file = directory / "data.parquet"
    if not file.exists():
        file = directory / "rows.parquet"
    with duckdb.connect() as con:
        source_sql = dataset_source(dataset_id)
        columns = [
            Column(name=r[0], type=r[1])
            for r in con.execute(f"DESCRIBE SELECT * FROM {source_sql}").fetchall()
        ]
        row_count = con.execute(f"SELECT count(*) FROM {source_sql}").fetchone()[0]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO datasets (id, name, source, row_count, size_bytes, columns, created_at,"
            " parent_id, branch) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dataset_id,
                name,
                source,
                row_count,
                file.stat().st_size,
                json.dumps([c.model_dump() for c in columns]),
                datetime.now(UTC).isoformat(),
                parent_id,
                branch,
            ),
        )
    return get_dataset(dataset_id)


# Datasets with the run that makes them, if any.
_SELECT = """
SELECT d.*,
    (SELECT json_object('id', r.id, 'status', r.status, 'done', r.done,
        'total', r.total) FROM runs r WHERE r.dataset_id = d.id) AS run
FROM datasets d
"""


def list_datasets() -> list[Dataset]:
    """Every dataset, newest first."""
    with db.connect() as conn:
        rows = conn.execute(f"{_SELECT} ORDER BY d.created_at DESC").fetchall()
    return [_from_row(row) for row in rows]


def get_dataset(dataset_id: str) -> Dataset:
    with db.connect() as conn:
        row = conn.execute(f"{_SELECT} WHERE d.id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    return _from_row(row)


def delete_files(dataset_id: str) -> None:
    """Remove a dataset's files, e.g. of one that was never recorded."""
    shutil.rmtree(_dataset_dir(dataset_id), ignore_errors=True)


def delete_dataset(dataset_id: str) -> None:
    """Delete a dataset with its jobs and the run that makes it. Datasets made from it stay."""
    get_dataset(dataset_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    delete_files(dataset_id)


def dataset_fields(dataset_id: str) -> dict[str, tuple[str, list[str]]]:
    """Every column and every path into struct columns, in column order.

    Maps the path, e.g. `actor.login`, to its type and the keys leading to it in a row,
    e.g. `["actor", "login"]`. Keys may contain dots themselves; the path is only for display.
    """
    with duckdb.connect() as con:
        relation = con.sql(f"SELECT * EXCLUDE ({ROW_ID}) FROM {dataset_source(dataset_id)}")
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
    with duckdb.connect() as con:
        rows = con.execute(f"SUMMARIZE SELECT {select} FROM {dataset_source(dataset_id)} AS t")
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
    sql_from = f"FROM {dataset_source(dataset_id)} AS t WHERE {where}"
    try:
        with duckdb.connect() as con:
            matched = con.execute(f"SELECT count(*) {sql_from}", params).fetchone()[0]
            total = min(matched, query.limit) if query.limit else matched
            size = max(0, min(query.page_size, total - query.offset))
            rows = con.execute(
                f"SELECT to_json(t) {sql_from} ORDER BY {_order(query.sort, types)} LIMIT ? OFFSET ?",
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
                f"SELECT to_json(t) FROM (SELECT * FROM {dataset_source(dataset_id)} "
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
        searchable = [sql_ident(c) for c in types if c != ROW_ID]
        where.append(
            "(" + " OR ".join(f"contains(lower(CAST({c} AS VARCHAR)), ?)" for c in searchable) + ")"
        )
        params += [selection.search.lower()] * len(searchable)
    for f in selection.filters:
        column = sql_ident(_check_column(f.column, types))
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


def _order(sort: list[Sort], types: dict[str, str]) -> str:
    """A SQL ORDER BY list for a sort; ties go by `__row_id`."""
    order = [
        f"{sql_ident(_check_column(s.column, types))} {'DESC' if s.desc else 'ASC'} NULLS LAST"
        for s in sort
    ]
    return ", ".join([*order, ROW_ID])


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
    run = json.loads(row["run"]) if row["run"] else None
    return Dataset(**{**dict(row), "columns": json.loads(row["columns"]), "run": run})


def _dataset_dir(dataset_id: str) -> Path:
    return db.data_dir() / "datasets" / dataset_id


def dataset_source(dataset_id: str) -> str:
    """A DuckDB table expression for a dataset's rows, including one a run is still making. A run's
    answer columns come right after `__row_id`, so the newest answers are first."""
    directory = _dataset_dir(dataset_id)
    if (directory / "data.parquet").exists():
        return f"read_parquet({sql_string(directory / 'data.parquet')})"
    rows = sql_string(directory / "rows.parquet")
    parts = sql_string(run_parts_dir(dataset_id) / "*.parquet")
    return (
        f"(SELECT {ROW_ID}, a.* EXCLUDE ({ROW_ID}), r.* EXCLUDE ({ROW_ID}) "
        f"FROM read_parquet({rows}) AS r "
        f"LEFT JOIN read_parquet({parts}) AS a USING ({ROW_ID}))"
    )


def sql_ident(name: str) -> str:
    """A column name quoted for SQL."""
    return '"' + name.replace('"', '""') + '"'


def sql_string(value: object) -> str:
    """A string literal for SQL."""
    return "'" + str(value).replace("'", "''") + "'"
