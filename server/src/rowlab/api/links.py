from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from rowlab.core import links
from rowlab.core.datasets import Dataset

# No sign-in: the token in the path is the permission (see `links`).
router = APIRouter(prefix="/v1/links", tags=["links"])


@router.post("/{token}", operation_id="uploadWithLink", status_code=201)
def upload_with_link(
    token: str, file: Annotated[UploadFile, File(description="File to upload.")]
) -> Dataset:
    """Add a dataset from a file, with an upload link instead of signing in."""
    return links.upload(token, file.file, file.filename or "upload")


@router.get(
    "/{token}",
    operation_id="downloadWithLink",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download_with_link(token: str) -> FileResponse:
    """Download a dataset, with a download link instead of signing in."""
    path, name = links.download(token)
    return FileResponse(path, filename=name, background=BackgroundTask(path.unlink))
