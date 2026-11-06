from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from rowlab.core import compare, datasets, exports, prompts
from rowlab.core.compare import CompareRequest, Comparison
from rowlab.core.datasets import ColumnProfile, Dataset, Query, QueryResult
from rowlab.core.errors import InvalidRequest
from rowlab.core.exports import ExportFormat, ExportRequest, ExportResult
from rowlab.core.prompts import RenderRequest, RenderResult

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


@router.post("", operation_id="createDataset", status_code=201)
def create_dataset(
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
        return datasets.upload_dataset(file.file, file.filename or "upload")
    return datasets.create_dataset(source, connection_id)


@router.get("", operation_id="listDatasets")
def list_datasets() -> list[Dataset]:
    return datasets.list_datasets()


@router.get("/{dataset_id}", operation_id="getDataset")
def get_dataset(dataset_id: str) -> Dataset:
    return datasets.get_dataset(dataset_id)


@router.delete("/{dataset_id}", operation_id="deleteDataset", status_code=204)
def delete_dataset(dataset_id: str) -> None:
    datasets.delete_dataset(dataset_id)


@router.get("/{dataset_id}/profile", operation_id="getDatasetProfile")
def profile_dataset(dataset_id: str) -> list[ColumnProfile]:
    return datasets.profile_dataset(dataset_id)


@router.post("/{dataset_id}/query", operation_id="queryDataset")
def query_dataset(dataset_id: str, query: Query) -> QueryResult:
    return datasets.query_dataset(dataset_id, query)


@router.post("/{dataset_id}/compare", operation_id="compareColumns")
def compare_columns(dataset_id: str, request: CompareRequest) -> Comparison:
    """How often two or more columns give the same value in each row: several models' answers,
    a model against labels someone already has, or any columns at all. With a `reference`, also
    each column's accuracy against it. Every count comes with the filter for its rows, to use in a
    scope's `filters`: to see them (`query`) or to ask about them again (`runs`)."""
    return compare.compare(dataset_id, request)


@router.post("/{dataset_id}/render", operation_id="renderPrompt")
def render_prompt(dataset_id: str, request: RenderRequest) -> RenderResult:
    """Render a prompt template for a page of rows, with warnings and token estimates."""
    return prompts.render_dataset(dataset_id, request)


@router.get(
    "/{dataset_id}/export",
    operation_id="downloadDataset",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download_dataset(
    dataset_id: str, format: ExportFormat, include_row_id: bool = False
) -> FileResponse:
    """Download the dataset as a CSV, JSONL or Parquet file, named after it. Nested values are JSON
    text in CSV. A dataset still being made can't be exported until its run is done."""
    path = exports.export_to_temp(dataset_id, format, include_row_id=include_row_id)
    return FileResponse(
        path,
        filename=exports.file_name(dataset_id, format),
        background=BackgroundTask(path.unlink),
    )


@router.post("/{dataset_id}/export", operation_id="exportDataset")
def export_dataset(dataset_id: str, request: ExportRequest) -> ExportResult:
    """Write the dataset as CSV, JSONL or Parquet to a file on the server, or to S3."""
    return exports.export_to_path(dataset_id, request)
