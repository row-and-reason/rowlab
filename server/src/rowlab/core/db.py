"""The app database: a SQLite file (local) or Postgres (hosted), behind one small interface.

Code writes SQL both understand, with `?` placeholders, and gets rows back as dicts. The one thing
only Postgres can do, several runners sharing the queue, is in `skip_locked`. Migrations
(`migrations/NNN_*.sql`, in SQL both understand) are applied once per process, when the database is
first used.
"""

import functools
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rowlab.core.config import config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_migrated: set[str] = set()
_migrating = threading.Lock()


class Connection:
    """A database connection taking `?` placeholders and returning rows as dicts."""

    def __init__(self, raw: Any, postgres: bool):
        self._raw = raw
        self._postgres = postgres

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        if self._postgres:
            sql = sql.replace("?", "%s")
        return self._raw.execute(sql, params)


def data_dir() -> Path:
    """Where rowlab keeps local state: temporary files, and the SQLite database by default."""
    return config().data_dir


@contextmanager
def connect() -> Iterator[Connection]:
    """Open the app database, migrated, and commit when the block succeeds."""
    url = config().database_url
    with _raw(url) as (raw, postgres):
        conn = Connection(raw, postgres)
        if url not in _migrated:
            with _migrating:
                if url not in _migrated:
                    _migrate(raw, postgres)
                    _migrated.add(url)
        yield conn


def close() -> None:
    """Close Postgres connection pools, e.g. when a test is done with its database."""
    for url in list(_migrated):
        if url.startswith(("postgresql://", "postgres://")):
            _pool(url).close()
    _pool.cache_clear()
    _migrated.clear()


def skip_locked() -> str:
    """For a `SELECT … LIMIT 1` that claims a row: on Postgres, so several runners each claim a
    different one. SQLite has one runner, and no such clause."""
    return " FOR UPDATE SKIP LOCKED" if config().postgres else ""


@contextmanager
def _raw(url: str) -> Iterator[tuple[Any, bool]]:
    if url.startswith(("postgresql://", "postgres://")):
        # Committed on leaving the block, rolled back if it raised.
        with _pool(url).connection() as raw:
            yield raw, True
        return
    path = Path(url.removeprefix("sqlite:///"))
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.row_factory = lambda cursor, row: {d[0]: v for d, v in zip(cursor.description, row)}
    raw.execute("PRAGMA foreign_keys = ON")
    # The runner thread writes while requests read; WAL lets them proceed side by side.
    raw.execute("PRAGMA journal_mode = WAL")
    try:
        with raw:
            yield raw, False
    finally:
        raw.close()


@functools.cache
def _pool(url: str) -> Any:
    from psycopg.rows import dict_row  # Only needed for Postgres: `pip install rowlab[hosted]`.
    from psycopg_pool import ConnectionPool

    # Up to 10 at once: requests, the runner thread, and calls that use a connection inside another.
    return ConnectionPool(url, kwargs={"row_factory": dict_row}, min_size=1, max_size=10, open=True)


def _migrate(raw: Any, postgres: bool) -> None:
    """Apply the migrations newer than the database's `schema_version`, each in one transaction."""
    raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = raw.execute("SELECT max(version) AS version FROM schema_version").fetchone()
    version = row["version"] or 0
    if not postgres and version == 0:
        legacy = raw.execute("PRAGMA user_version").fetchone()["user_version"]
        if legacy:
            raise RuntimeError(
                f"{data_dir()} holds a database from before rowlab's migrations were reset. "
                "Move that folder aside to start afresh."
            )
    for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        number = int(file.name.split("_")[0])
        if number <= version:
            continue
        if postgres:
            with raw.transaction():
                raw.execute(file.read_text())
                raw.execute("INSERT INTO schema_version VALUES (%s)", (number,))
        else:
            raw.executescript(
                f"BEGIN;\n{file.read_text()}\nINSERT INTO schema_version VALUES ({number});\nCOMMIT;"
            )
    raw.commit()
