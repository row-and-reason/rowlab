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
from rowlab.core import connections, db, storage
from rowlab.core.config import config
from rowlab.core.errors import InvalidRequest, NotFound

ROW_ID = "__row_id"
# In a run's part files: which answers failed, so they can be asked again. Not part of the dataset.
FAILED = "__failed"

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
    failed: int = Field(description="Answers that failed, which resuming asks again.")
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


def create_dataset(org_id: str, source: str, connection_id: str | None = None) -> Dataset:
    """Ingest a local file path, a public http(s) URL, or an `s3://bucket/key` object, read with the
    given connection or else the environment's AWS credentials."""
    if connections.is_s3(source):
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
    # Some hosts reject Python's default user agent.
    request = Request(url, headers={"User-Agent": f"rowlab/{__version__}"})
    try:
        with urlopen(request, timeout=60) as response, _temp_copy(response, name) as path:
            return _ingest_file(org_id, path, name=name, source=url)
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
            con.execute("SET temp_directory = ?", [str(db.data_dir() / "tmp")])
            if connections.is_s3(location):
                connections.configure(con, org_id, connection_id)
            for i, (_, reader) in enumerate(readers):
                try:
                    # A table keeps the file's row order, so `rowid` becomes a stable row id.
                    con.execute(f"CREATE TABLE src AS SELECT * FROM {reader}", [location])
                    break
                except duckdb.HTTPException:
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
    except duckdb.Error as e:
        storage.delete_dataset(dataset_id)
        raise InvalidRequest(f"Could not read {source}: {e}") from e
    except BaseException:
        storage.delete_dataset(dataset_id)
        raise

    return _register(dataset_id, org_id=org_id, name=name_without_extension(name), source=source)


def write_run_rows(parent_id: str, asked: list[int]) -> str:
    """Start the dataset a run makes: copy the parent's rows, so it doesn't depend on the parent, and
    list the ones the run asks about. Returns its id; it is recorded once the run's first (empty)
    part is written."""
    dataset_id = uuid.uuid4().hex
    storage.prepare(dataset_id)
    try:
        with storage.connect() as con:
            storage.write(
                con,
                f"SELECT * FROM {dataset_source(parent_id)}",
                storage.location(dataset_id, "rows.parquet"),
            )
            storage.write(
                con,
                f"SELECT unnest(?::BIGINT[]) AS {ROW_ID}",
                storage.location(dataset_id, "asked.parquet"),
                [asked],
            )
    except BaseException:
        storage.delete_dataset(dataset_id)
        raise
    return dataset_id


def register_run_dataset(dataset_id: str, parent_id: str) -> Dataset:
    """Record the dataset a run makes, once its rows and first (empty) part are written. It is named
    after its branch, numbered like an outline: `titanic__1` for the first made from `titanic`,
    `titanic__1.2` for the second made from `titanic__1`. Numbers aren't reused, so a name always
    means one dataset."""
    parent = get_dataset(parent_id)
    with db.connect() as conn:
        made = conn.execute(
            "UPDATE datasets SET made = made + 1 WHERE id = ? RETURNING made", (parent_id,)
        ).fetchone()["made"]
    branch = f"{parent.branch}.{made}" if parent.branch else str(made)
    base = parent.name.removesuffix(f"__{parent.branch}") if parent.branch else parent.name
    return _register(
        dataset_id,
        org_id=org_of(parent_id),
        name=f"{base}__{branch}",
        source=f"Made from {parent.name}",
        parent_id=parent_id,
        branch=branch,
    )


def finish_run_dataset(dataset_id: str) -> None:
    """Write a run's dataset out as one Parquet file, once every chunk is written. Its run's files
    stay, so failed answers can be asked again later (see `reopen_run_dataset`)."""
    data = storage.location(dataset_id, "data.parquet")
    with storage.connect() as con:
        storage.write(con, f"SELECT * FROM {dataset_source(dataset_id)} ORDER BY {ROW_ID}", data)
    with db.connect() as conn:
        conn.execute(
            "UPDATE datasets SET size_bytes = ? WHERE id = ?", (storage.size(data), dataset_id)
        )


def reopen_run_dataset(dataset_id: str) -> None:
    """Read a finished run's dataset from its run's files again, while the run asks its failed
    answers again; `finish_run_dataset` writes it out once more."""
    storage.delete(storage.location(dataset_id, "data.parquet"))


def read_run_part(dataset_id: str, name: str) -> dict[int, dict[str, Any]]:
    """The answers in one part a run wrote, by `__row_id`."""
    part = sql_string(storage.location(dataset_id, "parts", f"{name}.parquet"))
    with storage.connect() as con:
        rows = con.execute(f"SELECT to_json(t) FROM read_parquet({part}) AS t").fetchall()
    answers = {}
    for (data,) in rows:
        row = json.loads(data)
        answers[row.pop(ROW_ID)] = row
    return answers


def read_run_rows(dataset_id: str, *, offset: int, limit: int) -> list[dict[str, Any]]:
    """The rows a run asks about, by `__row_id`, without their answers."""
    rows_file = sql_string(storage.location(dataset_id, "rows.parquet"))
    asked_file = sql_string(storage.location(dataset_id, "asked.parquet"))
    with storage.connect() as con:
        rows = con.execute(
            f"SELECT to_json(t) FROM read_parquet({rows_file}) AS t "
            f"SEMI JOIN read_parquet({asked_file}) AS a USING ({ROW_ID}) ORDER BY {ROW_ID} "
            "LIMIT ? OFFSET ?",
            [limit, offset],
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def _register(
    dataset_id: str,
    *,
    org_id: str,
    name: str,
    source: str,
    parent_id: str | None = None,
    branch: str | None = None,
) -> Dataset:
    """Record a dataset whose files have been written."""
    file = storage.location(dataset_id, "data.parquet")
    if not storage.exists(file):
        file = storage.location(dataset_id, "rows.parquet")
    with storage.connect() as con:
        source_sql = dataset_source(dataset_id)
        columns = [
            Column(name=r[0], type=r[1])
            for r in con.execute(f"DESCRIBE SELECT * FROM {source_sql}").fetchall()
        ]
        row_count = con.execute(f"SELECT count(*) FROM {source_sql}").fetchone()[0]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO datasets (id, org_id, name, source, row_count, size_bytes, columns,"
            " created_at, parent_id, branch) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dataset_id,
                org_id,
                name,
                source,
                row_count,
                storage.size(file),
                json.dumps([c.model_dump() for c in columns]),
                datetime.now(UTC).isoformat(),
                parent_id,
                branch,
            ),
        )
    return get_dataset(dataset_id)


# Datasets with the run that makes them, if any.
_SELECT = """
SELECT d.*, r.id AS run_id, r.status AS run_status, r.done AS run_done, r.total AS run_total,
    r.costs AS run_costs
FROM datasets d LEFT JOIN runs r ON r.dataset_id = d.id
"""


def list_datasets(org_id: str) -> list[Dataset]:
    """The organisation's datasets, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            f"{_SELECT} WHERE d.org_id = ? ORDER BY d.created_at DESC", (org_id,)
        ).fetchall()
    return [_from_row(row) for row in rows]


def get_dataset(dataset_id: str) -> Dataset:
    with db.connect() as conn:
        row = conn.execute(f"{_SELECT} WHERE d.id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    return _from_row(row)


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
    """Delete a dataset with the run that makes it. Datasets made from it stay."""
    get_dataset(dataset_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    storage.delete_dataset(dataset_id)


def dataset_fields(dataset_id: str) -> dict[str, tuple[str, list[str]]]:
    """Every column and every path into struct columns, in column order.

    Maps the path, e.g. `actor.login`, to its type and the keys leading to it in a row,
    e.g. `["actor", "login"]`. Keys may contain dots themselves; the path is only for display.
    """
    with storage.connect() as con:
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
    with storage.connect() as con:
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


def _from_row(row: dict[str, Any]) -> Dataset:
    run = None
    if row["run_id"]:
        run = DatasetRun(
            id=row["run_id"],
            status=row["run_status"],
            done=row["run_done"],
            total=row["run_total"],
            failed=sum(cost["failed"] for cost in json.loads(row["run_costs"])),
        )
    return Dataset(**{**row, "columns": json.loads(row["columns"]), "run": run})


def dataset_source(dataset_id: str) -> str:
    """A DuckDB table expression for a dataset's rows, including one a run is still making. A run's
    answer columns come right after `__row_id`, so the newest answers are first."""
    data = storage.location(dataset_id, "data.parquet")
    if storage.exists(data):
        return f"read_parquet({sql_string(data)})"
    rows = sql_string(storage.location(dataset_id, "rows.parquet"))
    parts = sql_string(storage.location(dataset_id, "parts", "*.parquet"))
    return (
        f"(SELECT {ROW_ID}, a.* EXCLUDE ({ROW_ID}, {FAILED}), r.* EXCLUDE ({ROW_ID}) "
        f"FROM read_parquet({rows}) AS r "
        f"LEFT JOIN read_parquet({parts}) AS a USING ({ROW_ID}))"
    )


def sql_ident(name: str) -> str:
    """A column name quoted for SQL."""
    return '"' + name.replace('"', '""') + '"'


def sql_string(value: object) -> str:
    """A string literal for SQL."""
    return "'" + str(value).replace("'", "''") + "'"
