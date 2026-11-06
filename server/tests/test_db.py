from rowlab.core import db


def test_connections_can_be_used_inside_each_other():
    # E.g. a request reading a dataset while it records a run: on Postgres each needs its own
    # connection from the pool.
    with db.connect() as outer:
        outer.execute("SELECT 1 AS one").fetchone()
        with db.connect() as inner:
            assert inner.execute("SELECT 2 AS two").fetchone() == {"two": 2}
