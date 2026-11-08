"""Links that work without signing in, for a short while: an agent hands one to curl to upload a file
as a dataset, or to download one. They are for agents that reach rowlab over MCP and can neither send
it a file nor be sent one, nor read the server's disk. A link acts for the organisation that made it;
its token is sealed with `ROWLAB_SECRET_KEY`, so `hosted` mode only. Locally, paths do the same.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Literal

from pydantic import BaseModel, Field

from rowlab.core import crypto, datasets, exports, sql
from rowlab.core.config import config
from rowlab.core.datasets import Dataset
from rowlab.core.errors import InvalidRequest, Unauthorized
from rowlab.core.exports import ExportFormat

LINK_SECONDS = 15 * 60


class Link(BaseModel):
    url: str
    expires_at: datetime
    command: str = Field(description="How to use it, e.g. from a shell.")


def upload_link(org_id: str) -> Link:
    """A link to POST one file to as `file`, which becomes a dataset in the organisation."""
    link = _make("upload", {"org_id": org_id})
    return link.model_copy(update={"command": f"curl -fsS -F 'file=@<path>' '{link.url}'"})


def download_link(
    dataset_id: str, fmt: ExportFormat, *, include_row_id: bool, query: str | None = None
) -> Link:
    """A link to GET the dataset, or the rows `query` picks, as a file."""
    if query is not None:
        sql.count(dataset_id, query)  # A wrong query says so now, not when the link is used.
    link = _make(
        "download",
        {"dataset_id": dataset_id, "format": fmt, "include_row_id": include_row_id, "sql": query},
    )
    name = exports.file_name(dataset_id, fmt)
    return link.model_copy(update={"command": f"curl -fsS -o '{name}' '{link.url}'"})


def upload(token: str, file: BinaryIO, filename: str) -> Dataset:
    return datasets.upload_dataset(_open("upload", token)["org_id"], file, filename)


def download(token: str) -> tuple[Path, str]:
    """The file, which the caller deletes, and its name."""
    found = _open("download", token)
    path = exports.export_to_temp(
        found["dataset_id"],
        found["format"],
        include_row_id=found["include_row_id"],
        query=found["sql"],
    )
    return path, exports.file_name(found["dataset_id"], found["format"])


def _make(purpose: Literal["upload", "download"], data: dict[str, Any]) -> Link:
    if not (config().url and config().secret_key):
        raise InvalidRequest("Links are for hosted rowlab; locally, give a path on this machine.")
    token = crypto.seal(json.dumps({"for": purpose, **data}))
    return Link(
        url=f"{config().url}/v1/links/{token}",
        expires_at=datetime.now(UTC) + timedelta(seconds=LINK_SECONDS),
        command="",
    )


def _open(purpose: Literal["upload", "download"], token: str) -> dict[str, Any]:
    opened = crypto.unseal(token, LINK_SECONDS) if config().secret_key else None
    found = json.loads(opened) if opened else None
    if found is None or found["for"] != purpose:
        raise Unauthorized("That link isn't valid, or it has expired: ask for a new one.")
    return found
