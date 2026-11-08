"""Model replies, kept so a paid call is not made twice, without the database growing with every row.

A run writes each chunk's replies to its dataset beside the chunk's part: `answers/part-{k}.parquet`,
with `__row_id`, the request's `key` (a hash of the organisation and the request) and the reply's
`data`. When the run is done they are written out as one `answers.parquet`, sorted by `__row_id`.
They are deleted with the dataset.

Before asking, a run looks for each request's reply in the other datasets of its tree (the datasets
made from one added file, which share `__row_id`s) whose runs are done and used the same models, so a
run on all rows after a try on a few doesn't pay for those few again. Each such dataset is one file,
read only around the chunk's rows. The database only keeps the replies of chunks under way
(`answer_journal`), so a stop or crash before a chunk is written doesn't pay for them again either;
they are cleared once the chunk is written.
"""

import hashlib
import json
from typing import Any

from rowlab.core import db, storage
from rowlab.core.datasets import ROW_ID, sql_ident, sql_string
from rowlab.core.providers.openrouter import Request

# Rows per row group of `answers.parquet`: a chunk's lookup reads about one group of each file.
ROW_GROUP_ROWS = 5000

# A reply: its key, the row it is for, and its data.
Reply = tuple[str, int, Any]


def key(org_id: str, request: Request) -> str:
    """The same request from the same organisation gets the same key; each organisation has its
    own replies, which nobody else sees or gets for free."""
    return hashlib.sha256(
        json.dumps(
            {"org": org_id, "path": request.path, "body": request.body}, sort_keys=True
        ).encode()
    ).hexdigest()


def journaled(run_id: str) -> dict[str, Any]:
    """The replies the run paid for in chunks not yet written, by key."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT key, data FROM answer_journal WHERE run_id = ?", (run_id,)
        ).fetchall()
    return {r["key"]: json.loads(r["data"]) for r in rows}


def stored(dataset_id: str, models: list[str], row_ids: list[int]) -> dict[str, Any]:
    """Replies kept by the other datasets of the tree whose runs are done and used any of `models`,
    for rows in the range of `row_ids`, by key. One file each, read only around those rows."""
    with db.connect() as conn:
        related = conn.execute(
            "SELECT d.id, r.config FROM datasets d JOIN runs r ON r.dataset_id = d.id"
            " WHERE d.root_id = (SELECT root_id FROM datasets WHERE id = ?) AND d.id <> ?",
            (dataset_id, dataset_id),
        ).fetchall()
    files = [
        file
        for r in related
        if set(models) & {m for task in json.loads(r["config"])["tasks"] for m in task["models"]}
        and storage.exists(file := storage.location(r["id"], "answers.parquet"))
    ]
    if not files or not row_ids:
        return {}
    with storage.connect() as con:
        rows = con.execute(
            f"SELECT key, data FROM read_parquet([{', '.join(map(sql_string, files))}])"
            f" WHERE {sql_ident(ROW_ID)} BETWEEN ? AND ?",
            [min(row_ids), max(row_ids)],
        ).fetchall()
    return {k: json.loads(data) for k, data in rows}


def journal(run_id: str, replies: list[Reply]) -> None:
    """Keep replies just paid for until their chunk is written."""
    if not replies:
        return
    with db.connect() as conn:
        for reply_key, row_id, data in replies:
            conn.execute(
                "INSERT INTO answer_journal (run_id, key, row_id, data) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (run_id, key) DO UPDATE SET data = excluded.data",
                (run_id, reply_key, row_id, json.dumps(data)),
            )


def clear_journal(run_id: str, row_ids: list[int]) -> None:
    """Forget the run's journaled replies for a chunk's rows, once it is written with them. A
    chunk's rows are a range of `__row_id`s no other chunk's overlap."""
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM answer_journal WHERE run_id = ? AND row_id BETWEEN ? AND ?",
            (run_id, min(row_ids), max(row_ids)),
        )


def write_part(dataset_id: str, name: str, replies: list[Reply]) -> None:
    """Write a chunk's replies beside its part, adding to any written before (a chunk whose failed
    answers are asked again keeps the rest)."""
    file = storage.location(dataset_id, "answers", f"{name}.parquet")
    # By row and key: rows with the same prompt share a key, and each row needs its reply.
    kept = {}
    if storage.exists(file):
        with storage.connect() as con:
            rows = con.execute(
                f"SELECT key, {sql_ident(ROW_ID)}, data FROM read_parquet({sql_string(file)})"
            ).fetchall()
        kept = {(row_id, k): (k, row_id, json.loads(data)) for k, row_id, data in rows}
    kept |= {(reply[1], reply[0]): reply for reply in replies}
    with storage.connect() as con:
        con.execute(f"CREATE TABLE answers ({sql_ident(ROW_ID)} BIGINT, key VARCHAR, data VARCHAR)")
        if kept:
            con.executemany(
                "INSERT INTO answers VALUES (?, ?, ?)",
                [(row_id, k, json.dumps(data)) for k, row_id, data in kept.values()],
            )
        storage.write(con, f"SELECT * FROM answers ORDER BY {sql_ident(ROW_ID)}", file)


def finish(dataset_id: str) -> None:
    """Write a done run's replies out as one file, sorted by `__row_id` so lookups read little of
    it; other runs reuse them from then on. The parts stay, like the run's, for asking failed answers
    again."""
    # An empty part, so there is one even for a run with none (one started before replies were
    # kept with datasets, say).
    write_part(dataset_id, "part-schema", [])
    parts = sql_string(storage.location(dataset_id, "answers", "*.parquet"))
    with storage.connect() as con:
        storage.write(
            con,
            f"SELECT * FROM read_parquet({parts}) ORDER BY {sql_ident(ROW_ID)}",
            storage.location(dataset_id, "answers.parquet"),
            row_group_size=ROW_GROUP_ROWS,
        )
