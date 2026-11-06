"""SQL over a dataset: how rows are picked, viewed, run on and exported.

A query is one DuckDB `SELECT` over the table `data`, the dataset, e.g.
`SELECT * FROM data WHERE stars = 1 ORDER BY review LIMIT 20`. It runs in a connection that can only
read that dataset's own files: no other files, no writing, no settings. To pick rows for a run, an
estimate or an export, it must return `__row_id`, as `SELECT *` does.

Comparing columns has functions of its own, taking a list of values:
- `agree([a, b, …])`: every value is there, and they are all the same.
- `disagree([a, b, …])`: at least two values differ (missing values don't count).
- `agree_within([a, b, …], tolerance)` and `disagree_within(…)`: the same for numbers, which count as
  the same when they are no further apart than `tolerance`.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import datasets, storage
from rowlab.core.datasets import ROW_ID, Column, sql_string
from rowlab.core.errors import InvalidRequest

ALL_ROWS = "SELECT * FROM data"

_MACROS = [
    (
        "CREATE MACRO agree(vals) AS len(list_filter(vals, lambda v: v IS NOT NULL)) = len(vals)"
        " AND len(list_distinct(vals)) = 1"
    ),
    "CREATE MACRO disagree(vals) AS len(list_distinct(vals)) > 1",
    (
        "CREATE MACRO agree_within(vals, tolerance) AS"
        " len(list_filter(vals, lambda v: v IS NOT NULL)) = len(vals)"
        " AND list_max(vals) - list_min(vals) <= tolerance"
    ),
    (
        "CREATE MACRO disagree_within(vals, tolerance) AS"
        " coalesce(list_max(vals) - list_min(vals), 0) > tolerance"
    ),
]


class QueryRequest(BaseModel):
    sql: str = Field(ALL_ROWS, description="One DuckDB `SELECT` over the table `data`.")
    offset: int = Field(0, ge=0)
    limit: int = Field(
        100, ge=1, le=1000, description="Rows to return; the query's own `LIMIT` caps the total."
    )


class QueryResult(BaseModel):
    columns: list[Column] = Field(
        description="What the query returns, which needn't be the dataset's."
    )
    rows: list[dict[str, Any]]
    total: int = Field(description="Rows the query returns, ignoring `offset` and `limit`.")


@contextmanager
def connect(dataset_id: str) -> Iterator[duckdb.DuckDBPyConnection]:
    """A DuckDB connection with the dataset as `data` and the compare functions, that can read
    nothing else and write nothing at all."""
    datasets.get_dataset(dataset_id)
    source = datasets.dataset_source(dataset_id)
    with storage.connect() as con:
        con.execute(f"CREATE VIEW data AS SELECT * FROM {source}")
        for macro in _MACROS:
            con.execute(macro)
        con.execute(f"SET allowed_directories = [{sql_string(storage.folder(dataset_id))}]")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        yield con


def check(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    """The query, if it is one `SELECT`; its trailing semicolon dropped."""
    try:
        statements = con.extract_statements(sql)
    except duckdb.Error as e:
        raise InvalidRequest(f"The SQL has an error: {e}") from e
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise InvalidRequest("Write one SELECT over the table `data`.")
    return sql.strip().rstrip(";")


def execute(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    """Run SQL built around a user's query, with its errors as invalid requests."""
    try:
        return con.execute(sql, params or [])
    except duckdb.Error as e:
        raise InvalidRequest(f"The SQL has an error: {e}") from e


def query(dataset_id: str, request: QueryRequest) -> QueryResult:
    """A page of what a query returns, and how many rows it returns in all."""
    with connect(dataset_id) as con:
        sql = check(con, request.sql)
        total = execute(con, f"SELECT count(*) FROM ({sql})").fetchone()[0]
        page = execute(
            con,
            f"SELECT to_json(q) FROM ({sql}) AS q LIMIT ? OFFSET ?",
            [request.limit, request.offset],
        )
        rows = [json.loads(r[0]) for r in page.fetchall()]
        columns = [
            Column(name=r[0], type=r[1])
            for r in execute(con, f"DESCRIBE SELECT * FROM ({sql})").fetchall()
        ]
    return QueryResult(columns=columns, rows=rows, total=total)


def row_ids(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    """SQL for the `__row_id`s a query picks, checking that it returns them."""
    sql = check(con, sql)
    names = [r[0] for r in execute(con, f"DESCRIBE SELECT * FROM ({sql})").fetchall()]
    if ROW_ID not in names:
        raise InvalidRequest(f"The query must return `{ROW_ID}`, e.g. SELECT * FROM data …")
    return f"SELECT {ROW_ID} FROM ({sql})"


def count(dataset_id: str, sql: str) -> int:
    with connect(dataset_id) as con:
        return execute(con, f"SELECT count(*) FROM ({row_ids(con, sql)})").fetchone()[0]


def sample(dataset_id: str, sql: str, n: int) -> list[dict[str, Any]]:
    """Up to `n` of the rows a query picks, at random, the same ones on every call."""
    with connect(dataset_id) as con:
        sql = check(con, sql)
        rows = execute(
            con,
            f"SELECT to_json(q) FROM (SELECT * FROM ({sql})) AS q "
            f"USING SAMPLE reservoir({int(n)} ROWS) REPEATABLE (1)",
        ).fetchall()
    return [json.loads(r[0]) for r in rows]
