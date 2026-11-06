import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def data_dir() -> Path:
    """Where rowlab keeps its state: `~/.rowlab`, or `ROWLAB_DATA_DIR` if set."""
    return Path(os.environ.get("ROWLAB_DATA_DIR") or "~/.rowlab").expanduser()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the app database, apply pending migrations, and commit when the block succeeds."""
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path / "rowlab.db")
    conn.row_factory = sqlite3.Row
    try:
        migrate(conn)
        with conn:
            yield conn
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> None:
    """Apply `migrations/NNN_*.sql` files newer than the database's `user_version`, in order."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        number = int(file.name.split("_")[0])
        if number > version:
            conn.executescript(
                f"BEGIN;\n{file.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;"
            )
