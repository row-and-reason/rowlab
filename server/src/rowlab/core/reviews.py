"""Human labels, stored separately from source data and model answers.

One small Parquet sidecar holds reviewed columns, on disk or S3. Database locks serialize edits
across server processes. Runs copy the sidecar so children keep
their own reviewed labels, even if the parent is changed or deleted later.
"""

import json
import threading
from typing import Any

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import datasets, db, storage
from rowlab.core.config import config
from rowlab.core.datasets import ROW_ID, Column, sql_ident, sql_string
from rowlab.core.errors import InvalidRequest, NotFound

_lock = threading.Lock()


class ReviewRequest(BaseModel):
    row_id: int = Field(ge=0)
    column: str = Field(description="The answer column being reviewed. Its type is preserved.")
    value: Any = Field(description="The reviewed value, or null to clear it.")


def reviewed_column(column: str) -> str:
    return "reviewed_" + column.split("__", 1)[0]


def save_review(dataset_id: str, request: ReviewRequest) -> Column:
    with _lock, db.connect() as transaction:
        if config().postgres:
            transaction.execute("SELECT id FROM datasets WHERE id = ? FOR UPDATE", (dataset_id,))
        else:
            transaction.execute("BEGIN IMMEDIATE")
        dataset = datasets.get_dataset(dataset_id)
        if dataset.run and dataset.run.status in ("queued", "running", "stopping"):
            raise InvalidRequest("Wait for the run to finish before reviewing its answers.")
        source = next((c for c in dataset.columns if c.name == request.column), None)
        if source is None or source.name == ROW_ID or source.name.startswith("reviewed_"):
            raise InvalidRequest("Pick a source or answer column to review.")
        name = reviewed_column(source.name)
        path = storage.location(dataset_id, "reviews.parquet")
        with storage.connect() as con:
            base = datasets.dataset_source(dataset_id, include_reviews=False)
            if not con.execute(
                f"SELECT 1 FROM {base} WHERE {ROW_ID} = ?", [request.row_id]
            ).fetchone():
                raise NotFound(f"Row {request.row_id} not found")
            original = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {base}").fetchall()}
            if name in original:
                raise InvalidRequest(f"{name} is an original column; it cannot be overwritten.")
            if storage.exists(path):
                con.execute(
                    f"CREATE TABLE labels AS SELECT * FROM read_parquet({sql_string(path)})"
                )
            else:
                con.execute(f"CREATE TABLE labels ({ROW_ID} BIGINT PRIMARY KEY)")
            types = {r[0]: r[1] for r in con.execute("DESCRIBE labels").fetchall()}
            if name in types and types[name] != source.type:
                raise InvalidRequest("These answers have different types; review them separately.")
            if name not in types:
                con.execute(f"ALTER TABLE labels ADD COLUMN {sql_ident(name)} {source.type}")
            if (
                source.type == "BOOLEAN"
                and request.value is not None
                and not isinstance(request.value, bool)
            ):
                raise InvalidRequest("Choose yes or no.")
            if source.type in ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT") and (
                request.value is not None
                and (isinstance(request.value, bool) or not isinstance(request.value, int))
            ):
                raise InvalidRequest("Enter a whole number.")
            try:
                value = con.execute(
                    f"SELECT CAST(CAST(? AS JSON) AS {source.type})", [json.dumps(request.value)]
                ).fetchone()[0]
            except duckdb.Error as e:
                raise InvalidRequest(f"Enter a valid {source.type.lower()} value.") from e
            # JSON-to-VARCHAR includes quotes; a text label is the original string instead.
            if source.type == "VARCHAR":
                if request.value is not None and not isinstance(request.value, str):
                    raise InvalidRequest("Enter a text label.")
                value = request.value
            if not con.execute(
                f"SELECT 1 FROM labels WHERE {ROW_ID} = ?", [request.row_id]
            ).fetchone():
                con.execute(f"INSERT INTO labels ({ROW_ID}) VALUES (?)", [request.row_id])
            con.execute(
                f"UPDATE labels SET {sql_ident(name)} = ? WHERE {ROW_ID} = ?",
                [value, request.row_id],
            )
            storage.write(con, "SELECT * FROM labels", path)
        return Column(name=name, type=source.type)
