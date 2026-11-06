"""How this rowlab runs, read once from the environment.

There are two modes. `local` is one person on their own machine: no sign-in, files on the server's disk
allowed. `hosted` is shared: the protections a shared server needs are on (and sign-in, once it exists).
Everything else is configuration:

- `ROWLAB_MODE`: `local` (the default) or `hosted`.
- `ROWLAB_DATA_DIR`: where rowlab keeps local state (temporary files, the SQLite database by default);
  `~/.rowlab` by default.
- `ROWLAB_DATABASE_URL`: `postgresql://…`, or a SQLite file in the data folder by default.
- `ROWLAB_STORAGE_URL`: where datasets are kept: a folder (the data folder's `datasets` by default) or
  `s3://bucket/prefix`, with AWS credentials from the environment (`AWS_ENDPOINT_URL` for MinIO).
- `ROWLAB_SERVER_FILES`: whether datasets can be added from, and exported to, paths on the server's
  disk: on in `local` mode, off in `hosted` mode by default.
"""

import functools
import os
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
    data_dir = Path(os.environ.get("ROWLAB_DATA_DIR") or "~/.rowlab").expanduser()
    server_files = os.environ.get("ROWLAB_SERVER_FILES")
    return Config(
        mode=mode,
        data_dir=data_dir,
        database_url=os.environ.get("ROWLAB_DATABASE_URL") or f"sqlite:///{data_dir / 'rowlab.db'}",
        storage_url=(os.environ.get("ROWLAB_STORAGE_URL") or str(data_dir / "datasets")).rstrip(
            "/"
        ),
        server_files=mode == "local"
        if server_files is None
        else server_files.lower() in ("1", "true", "yes"),
    )
