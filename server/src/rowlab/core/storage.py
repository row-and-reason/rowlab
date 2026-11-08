"""Where datasets' files live: a local folder or an S3 bucket, as configured (`ROWLAB_STORAGE_URL`).

Files are read and written with DuckDB, which handles both: `connect()` gives a DuckDB connection that
can reach the storage. What DuckDB can't do on S3 (checking, sizing and deleting files) is done here.
On S3 the credentials come from the environment, as for any AWS tool: `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, and `AWS_ENDPOINT_URL` for MinIO or other S3-compatible storage.
"""

import os
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb

from rowlab.core.config import config
from rowlab.core.errors import InvalidRequest


def location(dataset_id: str, *names: str) -> str:
    """A dataset's folder, or a file in it, e.g. `location(id, "parts", "part-000001.parquet")`."""
    return "/".join([config().storage_url, dataset_id, *names])


def folder(dataset_id: str) -> str:
    """A dataset's folder, ending in `/`."""
    return location(dataset_id) + "/"


def prepare(dataset_id: str) -> None:
    """Make a new dataset's folders, where there are folders (not on S3)."""
    if not config().s3_storage:
        Path(location(dataset_id, "parts")).mkdir(parents=True)


@contextmanager
def connect(seconds: float | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    """A DuckDB connection that can read and write datasets' files, within the configured memory,
    threads and disk, and interrupted after `seconds` (by default ten times a query's limit, for
    adding and exporting datasets)."""
    limit = seconds or config().query_seconds * 10
    temp = config().data_dir / "tmp" / "duckdb"
    temp.mkdir(parents=True, exist_ok=True)
    settings = {
        "memory_limit": config().duckdb_memory,
        "threads": config().duckdb_threads,
        "temp_directory": str(temp),
        "max_temp_directory_size": config().duckdb_temp,
    }
    with duckdb.connect(config=settings) as con:
        done = threading.Event()

        def stop_at_the_limit() -> None:
            # Again and again: an interrupt only stops the statement running at the time.
            if done.wait(limit):
                return
            while True:
                con.interrupt()
                if done.wait(0.1):
                    return

        threading.Thread(target=stop_at_the_limit, daemon=True).start()
        try:
            configure(con)
            yield con
        except duckdb.InterruptException as e:
            raise InvalidRequest(
                f"That took longer than {limit:g} s, rowlab's limit (`ROWLAB_QUERY_SECONDS`). "
                "Narrow the query, or pick fewer rows."
            ) from e
        finally:
            done.set()


def configure(con: duckdb.DuckDBPyConnection) -> None:
    """Let a DuckDB connection reach the storage, if it is S3. The secret is scoped to the storage's
    bucket, so connections to other buckets keep their own."""
    if not config().s3_storage:
        return
    bucket = urlparse(config().storage_url).netloc
    # Scopes match as prefixes: the slash keeps it off `s3://<bucket>-other`.
    options = {"SCOPE": f"s3://{bucket}/", "REGION": _region()}
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        options["KEY_ID"] = os.environ["AWS_ACCESS_KEY_ID"]
        options["SECRET"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    else:
        options["PROVIDER"] = "credential_chain"
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        options["ENDPOINT"] = endpoint.removeprefix("https://").removeprefix("http://").rstrip("/")
        # Storage other than AWS is addressed by path: `endpoint/bucket/key`.
        options["URL_STYLE"] = "path"
        options["USE_SSL"] = not endpoint.startswith("http://")
    settings = ", ".join(
        f"{key} {value}"
        if isinstance(value, bool) or key == "PROVIDER"
        else f"{key} {_quote(value)}"
        for key, value in options.items()
    )
    con.execute(f"CREATE TEMPORARY SECRET rowlab_storage (TYPE s3, {settings})")


def write(
    con: duckdb.DuckDBPyConnection,
    query: str,
    target: str,
    params: list[Any] | None = None,
    *,
    row_group_size: int | None = None,
) -> None:
    """Write what a query returns to a Parquet file in one go: locally, to a temporary name that
    then replaces the file; on S3, where an object appears complete or not at all, directly. Small
    row groups let a reader filtering on a sorted column skip more of the file."""
    options = "FORMAT parquet" + (
        f", ROW_GROUP_SIZE {int(row_group_size)}" if row_group_size else ""
    )
    if config().s3_storage:
        con.execute(f"COPY ({query}) TO {_quote(target)} ({options})", params or [])
        return
    Path(target).parent.mkdir(exist_ok=True)
    temporary = f"{target}.tmp"
    con.execute(f"COPY ({query}) TO {_quote(temporary)} ({options})", params or [])
    os.replace(temporary, target)


def exists(target: str) -> bool:
    if not config().s3_storage:
        return Path(target).exists()
    return _size(*_split(target)) is not None


def size(target: str) -> int:
    if not config().s3_storage:
        return Path(target).stat().st_size
    found = _size(*_split(target))
    if found is None:
        raise FileNotFoundError(target)
    return found


def delete(target: str) -> None:
    """Delete a file, if it is there."""
    if not config().s3_storage:
        Path(target).unlink(missing_ok=True)
        return
    bucket, key = _split(target)
    _s3().delete_object(Bucket=bucket, Key=key)


def delete_dataset(dataset_id: str) -> None:
    """Delete everything in a dataset's folder."""
    if not config().s3_storage:
        shutil.rmtree(location(dataset_id), ignore_errors=True)
        return
    bucket, prefix = _split(folder(dataset_id))
    s3 = _s3()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})


def _size(bucket: str, key: str) -> int | None:
    from botocore.exceptions import ClientError

    try:
        return _s3().head_object(Bucket=bucket, Key=key)["ContentLength"]
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def _s3() -> Any:
    import boto3  # Only needed for storage on S3: `pip install rowlab[hosted]`.

    return boto3.client("s3", region_name=_region())


def _split(target: str) -> tuple[str, str]:
    parsed = urlparse(target)
    return parsed.netloc, parsed.path.lstrip("/")


def _region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def check_not_storage(uri: str) -> None:
    """Raise InvalidRequest if an `s3://` source or export is in the bucket rowlab keeps datasets in:
    rowlab's own credentials reach it, and other organisations' datasets are there."""
    if config().s3_storage and _split(uri)[0] == _split(config().storage_url)[0]:
        raise InvalidRequest("That bucket is where rowlab keeps datasets. Use another one.")
