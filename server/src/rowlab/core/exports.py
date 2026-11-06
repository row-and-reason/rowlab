"""Exports: a dataset written out as a CSV, JSONL or Parquet file, the format picked at export time."""

import os
import tempfile
from pathlib import Path
from typing import Literal

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import datasets, db
from rowlab.core.datasets import ROW_ID, sql_ident, sql_string
from rowlab.core.errors import InvalidRequest
from rowlab.core.runs import ACTIVE

ExportFormat = Literal["csv", "jsonl", "parquet"]

EXTENSIONS: dict[ExportFormat, str] = {"csv": ".csv", "jsonl": ".jsonl", "parquet": ".parquet"}

# DuckDB COPY options per format.
_COPY_OPTIONS: dict[ExportFormat, str] = {
    "csv": "FORMAT csv, HEADER true",
    "jsonl": "FORMAT json",
    "parquet": "FORMAT parquet",
}


class ExportRequest(BaseModel):
    format: ExportFormat
    path: str = Field(
        description="Where to write it on the server: a file, or a folder to put `<name>.<format>` in."
    )
    include_row_id: bool = Field(False, description=f"Keep `{ROW_ID}`, rowlab's row number.")


class ExportResult(BaseModel):
    path: str
    size_bytes: int


def file_name(dataset_id: str, fmt: ExportFormat) -> str:
    return datasets.get_dataset(dataset_id).name + EXTENSIONS[fmt]


def export_to_temp(dataset_id: str, fmt: ExportFormat, *, include_row_id: bool) -> Path:
    """Write the dataset to a new temporary file, for a download; the caller deletes it."""
    tmp_dir = db.data_dir() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=EXTENSIONS[fmt], dir=tmp_dir)
    os.close(handle)
    path = Path(name)
    try:
        _write(dataset_id, fmt, path, include_row_id=include_row_id)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def export_to_path(dataset_id: str, request: ExportRequest) -> ExportResult:
    """Write the dataset to a path on the server, replacing a file that is there."""
    path = Path(request.path).expanduser()
    if path.is_dir():
        path = path / file_name(dataset_id, request.format)
    if not path.parent.is_dir():
        raise InvalidRequest(f"Folder not found: {path.parent}")
    # Written next to it first, so the file is complete or untouched.
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        _write(dataset_id, request.format, temporary, include_row_id=request.include_row_id)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return ExportResult(path=str(path.resolve()), size_bytes=path.stat().st_size)


def _write(dataset_id: str, fmt: ExportFormat, path: Path, *, include_row_id: bool) -> None:
    dataset = datasets.get_dataset(dataset_id)
    if dataset.run and dataset.run.status in ACTIVE:
        raise InvalidRequest(f"{dataset.name} is still being made. Export it once its run is done.")
    columns = []
    for column in dataset.columns:
        if column.name == ROW_ID and not include_row_id:
            continue
        name = sql_ident(column.name)
        # CSV has no nested values: structs, lists and maps go in as JSON text.
        nested = any(t in column.type for t in ("STRUCT", "MAP", "[]"))
        columns.append(
            f"CAST(to_json({name}) AS VARCHAR) AS {name}" if fmt == "csv" and nested else name
        )
    with duckdb.connect() as con:
        con.execute(
            f"COPY (SELECT {', '.join(columns)} FROM {datasets.dataset_source(dataset_id)} "
            f"ORDER BY {ROW_ID}) TO {sql_string(path)} ({_COPY_OPTIONS[fmt]})"
        )
