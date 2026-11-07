import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from rowlab.core import db
from rowlab.core.config import config


def test_connections_can_be_used_inside_each_other():
    # E.g. a request reading a dataset while it records a run: on Postgres each needs its own
    # connection from the pool.
    with db.connect() as outer:
        outer.execute("SELECT 1 AS one").fetchone()
        with db.connect() as inner:
            assert inner.execute("SELECT 2 AS two").fetchone() == {"two": 2}


def test_processes_starting_together_migrate_once():
    # The API and its runners start at the same time, each with a process of its own.
    if not config().postgres:
        pytest.skip("SQLite has one process")
    import psycopg
    from psycopg.rows import dict_row

    barrier = threading.Barrier(2)

    def start() -> None:
        with psycopg.connect(config().database_url, row_factory=dict_row) as raw:
            barrier.wait()
            db._migrate(raw, postgres=True)

    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(start) for _ in range(2)]:
            future.result()
    with db.connect() as conn:
        versions = conn.execute("SELECT version FROM schema_version").fetchall()
    assert len(versions) == len(list(db.MIGRATIONS_DIR.glob("*.sql")))
