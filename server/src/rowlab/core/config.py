"""How this rowlab runs, read once from the environment.

There are two modes. `local` is one person on their own machine: no sign-in, the server's own files and
network allowed. `hosted` is shared: people sign in with WorkOS, and the protections a shared server
needs are on. Everything else is configuration:

- `ROWLAB_MODE`: `local` (the default) or `hosted`.
- `ROWLAB_DATA_DIR`: where rowlab keeps local state (temporary files, the SQLite database by default);
  `~/.rowlab` by default.
- `ROWLAB_DATABASE_URL`: `postgresql://…`, or a SQLite file in the data folder by default.
- `ROWLAB_STORAGE_URL`: where datasets are kept: a folder (the data folder's `datasets` by default) or
  `s3://bucket/prefix`, with AWS credentials from the environment (`AWS_ENDPOINT_URL` for MinIO).
- `ROWLAB_SERVER_FILES`: whether datasets can be added from, and exported to, the server's own files:
  paths on its disk, and buckets its AWS credentials reach. On in `local` mode, off in `hosted` mode by
  default.
- `ROWLAB_PRIVATE_URLS`: whether web sources and S3 endpoints may be private addresses (localhost, the
  local network, cloud metadata). On in `local` mode, off in `hosted` mode by default.
- `ROWLAB_URL`: where people reach rowlab, e.g. `https://rowlab.example.com`; `hosted` mode only.
- `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`: the WorkOS project people sign in with; `hosted` mode only.
- `ROWLAB_SECRET_KEY`: encrypts saved keys (OpenRouter, S3); any long random string. Required in
  `hosted` mode; locally, keys are kept as they are without it.

Limits, the same in both modes; raise them for bigger data:

- `ROWLAB_DUCKDB_MEMORY` (`1GB`), `ROWLAB_DUCKDB_THREADS` (`2`): per DuckDB connection; past the
  memory, DuckDB spills to disk, up to `ROWLAB_DUCKDB_TEMP` (`10GB`).
- `ROWLAB_QUERY_SECONDS` (`30`): per query; adding and exporting a dataset get ten times as long.
- `ROWLAB_MAX_FILE` (`1GB`): the largest file that can be uploaded, downloaded or read from S3.
- `ROWLAB_RUNS_PER_ORG` (`2`): runs one organisation has going at once; the rest wait their turn.
- `ROWLAB_RUN_WAIT_SECONDS` (`300`): a run waiting this long goes next, before shorter ones.
"""

import functools
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Config:
    mode: Literal["local", "hosted"]
    data_dir: Path
    database_url: str
    storage_url: str
    server_files: bool
    private_urls: bool
    url: str
    workos_client_id: str
    workos_api_key: str
    secret_key: str
    duckdb_memory: str
    duckdb_threads: int
    duckdb_temp: str
    query_seconds: float
    max_file_bytes: int
    runs_per_org: int
    run_wait_seconds: float

    @property
    def postgres(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgres://"))

    @property
    def s3_storage(self) -> bool:
        return self.storage_url.startswith("s3://")


@functools.cache
def config() -> Config:
    mode = os.environ.get("ROWLAB_MODE", "local")
    if mode not in ("local", "hosted"):
        raise ValueError(f"ROWLAB_MODE must be local or hosted, not {mode!r}.")
    local = mode == "local"
    data_dir = Path(os.environ.get("ROWLAB_DATA_DIR") or "~/.rowlab").expanduser()
    hosted = {
        name: os.environ.get(name, "")
        for name in ("ROWLAB_URL", "WORKOS_CLIENT_ID", "WORKOS_API_KEY", "ROWLAB_SECRET_KEY")
    }
    missing = [name for name, value in hosted.items() if not value]
    if not local and missing:
        raise ValueError(f"Hosted mode needs {', '.join(missing)}.")
    return Config(
        mode=mode,
        data_dir=data_dir,
        database_url=os.environ.get("ROWLAB_DATABASE_URL") or f"sqlite:///{data_dir / 'rowlab.db'}",
        storage_url=(os.environ.get("ROWLAB_STORAGE_URL") or str(data_dir / "datasets")).rstrip(
            "/"
        ),
        server_files=_flag("ROWLAB_SERVER_FILES", local),
        private_urls=_flag("ROWLAB_PRIVATE_URLS", local),
        url=hosted["ROWLAB_URL"].rstrip("/"),
        workos_client_id=hosted["WORKOS_CLIENT_ID"],
        workos_api_key=hosted["WORKOS_API_KEY"],
        secret_key=hosted["ROWLAB_SECRET_KEY"],
        duckdb_memory=_size("ROWLAB_DUCKDB_MEMORY", "1GB")[0],
        duckdb_threads=_number("ROWLAB_DUCKDB_THREADS", 2, int),
        duckdb_temp=_size("ROWLAB_DUCKDB_TEMP", "10GB")[0],
        query_seconds=_number("ROWLAB_QUERY_SECONDS", 30, float),
        max_file_bytes=_size("ROWLAB_MAX_FILE", "1GB")[1],
        runs_per_org=_number("ROWLAB_RUNS_PER_ORG", 2, int),
        run_wait_seconds=_number("ROWLAB_RUN_WAIT_SECONDS", 300, float),
    )


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.lower() in ("1", "true", "yes")


def _number(name: str, default: float, kind: type) -> float:
    value = os.environ.get(name) or str(default)
    try:
        number = kind(value)
    except ValueError:
        raise ValueError(f"{name} must be a number, not {value!r}.") from None
    if number <= 0:
        raise ValueError(f"{name} must be more than 0.")
    return number


_UNITS = {"": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}


def _size(name: str, default: str) -> tuple[str, int]:
    """A size like `1GB`, as written (for DuckDB) and in bytes."""
    value = (os.environ.get(name) or default).strip().upper()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)?", value)
    if not match:
        raise ValueError(f"{name} must be a size like 500MB or 2GB, not {value!r}.")
    return value, int(float(match[1]) * _UNITS[match[2] or ""])
