from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from rowlab.core import datasets
from rowlab.core.datasets import ColumnProfile, Dataset, Query, QueryResult
from rowlab.core.errors import InvalidRequest

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


@router.post("", operation_id="createDataset", status_code=201)
def create_dataset(
    file: Annotated[UploadFile | None, File(description="File to upload.")] = None,
    source: Annotated[
        str | None, Form(description="Path of a file on the server, or a public http(s) URL.")
    ] = None,
) -> Dataset:
    """Ingest a CSV, TSV, JSON, JSONL or Parquet file, optionally gzipped: either upload `file` or give
    a `source`. The format is detected from the file's content."""
    if (file is None) == (source is None):
        raise InvalidRequest("Give either `file` or `source`.")
    if file is not None:
        return datasets.upload_dataset(file.file, file.filename or "upload")
    return datasets.create_dataset(source)


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
