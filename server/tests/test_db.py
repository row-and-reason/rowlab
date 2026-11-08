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


def test_the_answers_migration_finds_each_datasets_tree():
    # A tree whose middle dataset was deleted: what was made from it stays in the tree.
    sql = (db.MIGRATIONS_DIR / "005_answers.sql").read_text()
    backfill = sql[sql.index("WITH RECURSIVE") : sql.index("CREATE INDEX")]
    made = [("root", None), ("child", "root"), ("orphan", "deleted"), ("grandchild", "child")]
    with db.connect() as conn:
        for id_, parent in made:
            conn.execute(
                "INSERT INTO datasets (id, org_id, name, source, row_count, size_bytes, columns,"
                " created_at, parent_id) VALUES (?, 'local', ?, '', 0, 0, '[]', '', ?)",
                (id_, id_, parent),
            )
        conn.execute(backfill)
        roots = conn.execute("SELECT id, root_id FROM datasets").fetchall()
    assert {r["id"]: r["root_id"] for r in roots} == {
        "root": "root",
        "child": "root",
        "grandchild": "root",
        "orphan": "deleted",
    }
