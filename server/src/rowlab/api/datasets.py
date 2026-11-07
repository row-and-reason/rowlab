from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from rowlab.api.auth import CanEdit, CanRead
from rowlab.core import compare, datasets, exports, prompts, sql
from rowlab.core.compare import CompareRequest, Comparison
from rowlab.core.datasets import ColumnProfile, Dataset
from rowlab.core.errors import InvalidRequest
from rowlab.core.exports import ExportFormat, ExportRequest, ExportResult
from rowlab.core.prompts import RenderRequest, RenderResult
from rowlab.core.sql import QueryRequest, QueryResult

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


@router.post("", operation_id="createDataset", status_code=201)
def create_dataset(
    me: CanEdit,
    file: Annotated[UploadFile | None, File(description="File to upload.")] = None,
    source: Annotated[
        str | None,
        Form(
            description="Path of a file on the server, a public http(s) URL, or an "
            "`s3://bucket/key` object."
        ),
    ] = None,
    connection_id: Annotated[
        str | None,
        Form(description="For `s3://` sources; without one, the environment's AWS credentials."),
    ] = None,
) -> Dataset:
    """Ingest a CSV, TSV, JSON, JSONL or Parquet file, optionally gzipped: either upload `file` or give
    a `source`. The format is detected from the file's content."""
    if (file is None) == (source is None):
        raise InvalidRequest("Give either `file` or `source`.")
    if file is not None:
        return datasets.upload_dataset(me.org.id, file.file, file.filename or "upload")
    return datasets.create_dataset(me.org.id, source, connection_id)


@router.get("", operation_id="listDatasets")
def list_datasets(me: CanRead) -> list[Dataset]:
    return datasets.list_datasets(me.org.id)


@router.get("/{dataset_id}", operation_id="getDataset")
def get_dataset(dataset_id: str, me: CanRead) -> Dataset:
    datasets.check_access(me.org.id, dataset_id)
    return datasets.get_dataset(dataset_id)


@router.patch("/{dataset_id}", operation_id="renameDataset")
def rename_dataset(dataset_id: str, request: datasets.RenameDataset, me: CanEdit) -> Dataset:
    datasets.check_access(me.org.id, dataset_id)
    return datasets.rename_dataset(dataset_id, request)


@router.delete("/{dataset_id}", operation_id="deleteDataset", status_code=204)
def delete_dataset(dataset_id: str, me: CanEdit) -> None:
    datasets.check_access(me.org.id, dataset_id)
    datasets.delete_dataset(dataset_id)


@router.get("/{dataset_id}/profile", operation_id="getDatasetProfile")
def profile_dataset(dataset_id: str, me: CanRead) -> list[ColumnProfile]:
    datasets.check_access(me.org.id, dataset_id)
    return datasets.profile_dataset(dataset_id)


@router.post("/{dataset_id}/query", operation_id="queryDataset")
def query_dataset(dataset_id: str, request: QueryRequest, me: CanRead) -> QueryResult:
    """Run one DuckDB `SELECT` over the table `data`, the dataset, and return a page of its rows,
    e.g. `SELECT * FROM data WHERE stars = 1 ORDER BY review LIMIT 20`. It can read nothing but the
    dataset. `agree([a, b, …])` and `disagree([a, b, …])` compare columns in a row; see
    `POST /v1/datasets/{id}/compare`."""
    datasets.check_access(me.org.id, dataset_id)
    return sql.query(dataset_id, request)


@router.post("/{dataset_id}/compare", operation_id="compareColumns")
def compare_columns(dataset_id: str, request: CompareRequest, me: CanRead) -> Comparison:
    """How often two or more columns give the same value in each row: several models' answers,
    a model against labels someone already has, or any columns at all. With a `reference`, also
    each column's accuracy against it. Every count comes with the filter for its rows, to use in a
    query's WHERE clause: to see them (`query`) or to ask about them again (`runs`)."""
    datasets.check_access(me.org.id, dataset_id)
    return compare.compare(dataset_id, request)


@router.post("/{dataset_id}/render", operation_id="renderPrompt")
def render_prompt(dataset_id: str, request: RenderRequest, me: CanRead) -> RenderResult:
    """Render a prompt template for a page of rows, with warnings and token estimates."""
    datasets.check_access(me.org.id, dataset_id)
    return prompts.render_dataset(dataset_id, request)


@router.get(
    "/{dataset_id}/export",
    operation_id="downloadDataset",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download_dataset(
    dataset_id: str,
    me: CanEdit,
    format: ExportFormat,
    include_row_id: bool = False,
    sql: Annotated[
        str | None, Query(description="Only the rows this query picks; it must return `__row_id`.")
    ] = None,
) -> FileResponse:
    """Download the dataset as a CSV, JSONL or Parquet file, named after it. Nested values are JSON
    text in CSV. A dataset still being made can't be exported until its run is done."""
    datasets.check_access(me.org.id, dataset_id)
    path = exports.export_to_temp(dataset_id, format, include_row_id=include_row_id, query=sql)
    return FileResponse(
        path,
        filename=exports.file_name(dataset_id, format),
        background=BackgroundTask(path.unlink),
    )


@router.post("/{dataset_id}/export", operation_id="exportDataset")
def export_dataset(dataset_id: str, request: ExportRequest, me: CanEdit) -> ExportResult:
    """Write the dataset as CSV, JSONL or Parquet to a file on the server, or to S3."""
    datasets.check_access(me.org.id, dataset_id)
    return exports.export_to_path(dataset_id, request)
